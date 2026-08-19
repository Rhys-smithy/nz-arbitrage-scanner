import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import tempfile
import time
import unittest
from unittest import mock

from scanner import scan_progress


class TestLoadProgress(unittest.TestCase):
    def test_missing_file_returns_well_formed_not_running_state(self):
        state = scan_progress.load_progress("/tmp/definitely_missing_scan_progress_xyz.json")
        self.assertFalse(state["running"])
        self.assertIsNone(state["stage"])
        # Every key a UI might read must be present even with nothing to
        # show, so the dashboard never has to guess at a missing key.
        for key in (
            "queries_completed", "queries_total", "raw_results", "unique_results",
            "candidates", "verified", "research_completed", "research_total",
            "decision_counts", "error", "heartbeat", "elapsed_seconds",
        ):
            self.assertIn(key, state)

    def test_corrupt_file_returns_not_running_state(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scan_progress.json")
            with open(path, "w") as f:
                f.write("{not valid json")
            state = scan_progress.load_progress(path)
            self.assertFalse(state["running"])
            self.assertIsNone(state["stage"])

    def test_non_dict_json_returns_not_running_state(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scan_progress.json")
            with open(path, "w") as f:
                json.dump([1, 2, 3], f)
            state = scan_progress.load_progress(path)
            self.assertFalse(state["running"])

    def test_sparse_persisted_dict_is_backfilled_with_defaults(self):
        # A hand-written or older-schema file missing keys must never
        # crash a reader that expects the full shape.
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scan_progress.json")
            with open(path, "w") as f:
                json.dump({"running": True, "stage": "SEARCH"}, f)
            state = scan_progress.load_progress(path)
            self.assertTrue(state["running"])
            self.assertEqual(state["stage"], "SEARCH")
            self.assertEqual(state["candidates"], 0)
            self.assertEqual(state["decision_counts"], {})


class TestSaveProgressAtomicity(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "scan_progress.json")
            state = {"running": True, "stage": "SEARCH", "queries_total": 5}
            scan_progress.save_progress(state, path)
            loaded = scan_progress.load_progress(path)
            self.assertEqual(loaded["running"], True)
            self.assertEqual(loaded["queries_total"], 5)

    def test_save_leaves_no_leftover_tempfile_on_success(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scan_progress.json")
            scan_progress.save_progress({"running": True}, path)
            entries = os.listdir(d)
            self.assertEqual(entries, ["scan_progress.json"])

    def test_save_uses_replace_not_in_place_write(self):
        # Real atomicity check: os.replace() is used (tempfile + rename),
        # not a direct open(path, "w") -- a reader polling this file mid-
        # write must never see a truncated/partial file. Verified by
        # spying on os.replace rather than by racing threads (which would
        # be flaky) -- this pins the *mechanism*, which is what actually
        # provides the guarantee.
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scan_progress.json")
            with mock.patch("scanner.scan_progress.os.replace", wraps=os.replace) as mock_replace:
                scan_progress.save_progress({"running": True}, path)
            mock_replace.assert_called_once()

    def test_failed_write_cleans_up_tempfile(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scan_progress.json")
            with mock.patch("scanner.scan_progress.os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    scan_progress.save_progress({"running": True}, path)
            # No stray .scan_progress_*.tmp file left behind.
            leftovers = [f for f in os.listdir(d) if f != "scan_progress.json"]
            self.assertEqual(leftovers, [])


class TestStartProgress(unittest.TestCase):
    def test_start_progress_resets_to_a_fresh_running_state(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scan_progress.json")
            # Leftover state from a previous run.
            scan_progress.save_progress(
                {"running": False, "stage": "COMPLETE", "decision_counts": {"BUY": 3}}, path
            )
            state = scan_progress.start_progress(queries_total=10, path=path)
            self.assertTrue(state["running"])
            self.assertEqual(state["stage"], scan_progress.STAGE_SEARCH)
            self.assertEqual(state["queries_total"], 10)
            # Previous run's decision_counts must not leak into a fresh run.
            self.assertEqual(state["decision_counts"], {})
            self.assertEqual(
                state["stage_status"],
                {"SEARCH": "active", "VALIDATION": "pending", "RESEARCH": "pending"},
            )

    def test_start_progress_sets_started_at_and_heartbeat(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scan_progress.json")
            before = time.time()
            state = scan_progress.start_progress(path=path)
            after = time.time()
            self.assertTrue(before <= state["started_at"] <= after)
            self.assertEqual(state["started_at"], state["heartbeat"])
            self.assertEqual(state["elapsed_seconds"], 0.0)


class TestUpdateProgress(unittest.TestCase):
    def test_update_progress_merges_onto_existing_state(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scan_progress.json")
            scan_progress.start_progress(queries_total=5, path=path)
            state = scan_progress.update_progress({"queries_completed": 2}, path=path)
            self.assertEqual(state["queries_completed"], 2)
            self.assertEqual(state["queries_total"], 5)  # untouched by the patch

    def test_update_progress_refreshes_heartbeat_and_elapsed(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scan_progress.json")
            started = scan_progress.start_progress(path=path)
            time.sleep(0.05)
            updated = scan_progress.update_progress({"queries_completed": 1}, path=path)
            self.assertGreater(updated["heartbeat"], started["heartbeat"])
            self.assertGreaterEqual(updated["elapsed_seconds"], 0.05)

    def test_update_progress_before_start_seeds_a_fresh_running_state(self):
        # Defensive path (see the function's own docstring) -- production
        # code always calls start_progress() first via main.py, but this
        # must not crash if it's ever called without that.
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scan_progress.json")
            state = scan_progress.update_progress({"queries_completed": 1}, path=path)
            self.assertTrue(state["running"])
            self.assertEqual(state["queries_completed"], 1)


class TestCompleteAndFailProgress(unittest.TestCase):
    def test_complete_progress_marks_not_running_with_decision_counts(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scan_progress.json")
            scan_progress.start_progress(queries_total=3, path=path)
            scan_progress.update_progress({"research_completed": 2, "research_total": 2}, path=path)
            state = scan_progress.complete_progress({"BUY": 1, "PASS": 1}, path=path)
            self.assertFalse(state["running"])
            self.assertEqual(state["stage"], scan_progress.STAGE_COMPLETE)
            self.assertEqual(state["decision_counts"], {"BUY": 1, "PASS": 1})
            self.assertEqual(
                state["stage_status"], {"SEARCH": "done", "VALIDATION": "done", "RESEARCH": "done"}
            )
            self.assertIsNotNone(state["completed_at"])
            # Real counts collected during the run must survive completion,
            # not be reset.
            self.assertEqual(state["research_completed"], 2)

    def test_fail_progress_preserves_whatever_progress_was_already_collected(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scan_progress.json")
            scan_progress.start_progress(queries_total=10, path=path)
            scan_progress.update_progress(
                {
                    "stage": scan_progress.STAGE_RESEARCH,
                    "queries_completed": 10,
                    "candidates": 4,
                    "verified": 3,
                    "research_completed": 1,
                    "research_total": 3,
                },
                path=path,
            )
            state = scan_progress.fail_progress("Discovery scan failed: boom", path=path)
            self.assertFalse(state["running"])
            self.assertEqual(state["stage"], scan_progress.STAGE_FAILED)
            self.assertEqual(state["error"], "Discovery scan failed: boom")
            # Nothing about the real progress already made is wiped.
            self.assertEqual(state["queries_completed"], 10)
            self.assertEqual(state["candidates"], 4)
            self.assertEqual(state["verified"], 3)
            self.assertEqual(state["research_completed"], 1)
            self.assertEqual(state["research_total"], 3)
            self.assertIsNotNone(state["completed_at"])

    def test_fail_progress_error_is_a_string_even_for_an_exception_object(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scan_progress.json")
            scan_progress.start_progress(path=path)
            state = scan_progress.fail_progress(ValueError("bad config"), path=path)
            self.assertEqual(state["error"], "bad config")
            self.assertIsInstance(state["error"], str)


if __name__ == "__main__":
    unittest.main()
