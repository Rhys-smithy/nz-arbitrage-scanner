import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import tempfile
import unittest

from scanner.hunting_store import make_key as hunting_make_key
from scanner.models import Opportunity
from scanner.pending_review_store import (
    STATUS_PENDING,
    STATUS_PURSUED,
    STATUS_REJECTED,
    active_pending_entries,
    get,
    load_pending_review_state,
    resolve_pursued,
    resolve_rejected,
    save_pending_review_state,
    sync_new_watch_opportunities,
)


def _watch_opportunity(url="https://www.turners.co.nz/x", title="Widget", flip_score=None):
    o = Opportunity(title=title, url=url, source="Turners", current_price=1.0)
    o.decision = "WATCH"
    o.flip_score = flip_score
    o.verification_status = "verified"
    return o


def _buy_opportunity(url="https://www.turners.co.nz/y"):
    o = Opportunity(title="Bargain", url=url, source="Turners", current_price=5.0)
    o.decision = "BUY"
    return o


class TestIdentityReusesHuntingStore(unittest.TestCase):
    def test_uses_the_exact_same_key_function_as_hunting_store(self):
        # Not a second, possibly-diverging identity system -- the same
        # canonicalize_url()-backed function, so a Pursue transition is a
        # trivial 1:1 key match into hunting_store's own dict.
        from scanner.pending_review_store import make_key as pr_make_key
        self.assertIs(pr_make_key, hunting_make_key)


class TestLoadSavePendingReviewState(unittest.TestCase):
    def test_load_missing_file_returns_empty_dict(self):
        self.assertEqual(load_pending_review_state("/tmp/definitely_does_not_exist_pending_12345.json"), {})

    def test_load_corrupt_file_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "pending_review_state.json")
            with open(path, "w") as f:
                f.write("{not valid json")
            self.assertEqual(load_pending_review_state(path), {})

    def test_load_non_dict_json_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "pending_review_state.json")
            with open(path, "w") as f:
                json.dump([1, 2, 3], f)
            self.assertEqual(load_pending_review_state(path), {})

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "pending_review_state.json")
            state = {}
            sync_new_watch_opportunities(state, [_watch_opportunity()])
            save_pending_review_state(state, path)
            self.assertEqual(load_pending_review_state(path), state)


class TestSyncNewWatchOpportunities(unittest.TestCase):
    def test_watch_opportunity_becomes_pending_entry(self):
        state = {}
        added = sync_new_watch_opportunities(state, [_watch_opportunity(title="Exercise Bike", flip_score=42)])
        self.assertEqual(len(added), 1)
        self.assertEqual(len(state), 1)
        entry = list(state.values())[0]
        self.assertEqual(entry["status"], STATUS_PENDING)
        self.assertEqual(entry["title"], "Exercise Bike")
        self.assertEqual(entry["flip_score"], 42)
        self.assertEqual(entry["source"], "Turners")
        self.assertIsNotNone(entry["found_at"])
        self.assertIsNotNone(entry["last_seen_at"])
        self.assertIsNone(entry["resolved_at"])

    def test_non_watch_decisions_are_ignored(self):
        state = {}
        added = sync_new_watch_opportunities(state, [_buy_opportunity()])
        self.assertEqual(added, [])
        self.assertEqual(state, {})

    def test_mixed_run_only_adds_watch_items(self):
        state = {}
        added = sync_new_watch_opportunities(
            state, [_buy_opportunity(), _watch_opportunity(url="https://www.turners.co.nz/z")]
        )
        self.assertEqual(len(added), 1)
        self.assertEqual(len(state), 1)

    def test_repeated_sighting_of_same_listing_does_not_duplicate(self):
        # Regression guard for "the same listing found repeatedly must
        # remain one review item".
        state = {}
        sync_new_watch_opportunities(state, [_watch_opportunity()])
        sync_new_watch_opportunities(state, [_watch_opportunity()])
        sync_new_watch_opportunities(state, [_watch_opportunity()])
        self.assertEqual(len(state), 1)

    def test_repeated_sighting_refreshes_last_seen_at_but_not_found_at(self):
        state = {}
        sync_new_watch_opportunities(state, [_watch_opportunity()])
        key = hunting_make_key("Turners", "https://www.turners.co.nz/x")
        original_found_at = state[key]["found_at"]
        state[key]["last_seen_at"] = "2000-01-01T00:00:00+00:00"  # force a detectably-stale value

        sync_new_watch_opportunities(state, [_watch_opportunity()])

        self.assertEqual(state[key]["found_at"], original_found_at)
        self.assertNotEqual(state[key]["last_seen_at"], "2000-01-01T00:00:00+00:00")

    def test_persists_across_multiple_scans_even_when_absent_from_a_later_run(self):
        # The core operational requirement: a WATCH item stays pending even
        # once a newer scan no longer finds it.
        state = {}
        opp_a = _watch_opportunity(url="https://www.turners.co.nz/a", title="Item A")
        opp_b = _watch_opportunity(url="https://www.turners.co.nz/b", title="Item B")

        sync_new_watch_opportunities(state, [opp_a])  # scan 1: only A
        self.assertEqual(len(state), 1)

        sync_new_watch_opportunities(state, [opp_b])  # scan 2: only B, A absent from this run
        self.assertEqual(len(state), 2)
        key_a = hunting_make_key("Turners", "https://www.turners.co.nz/a")
        self.assertIn(key_a, state)
        self.assertEqual(state[key_a]["status"], STATUS_PENDING)

    def test_different_urls_are_different_entries(self):
        state = {}
        sync_new_watch_opportunities(
            state,
            [
                _watch_opportunity(url="https://www.turners.co.nz/x"),
                _watch_opportunity(url="https://www.turners.co.nz/y"),
            ],
        )
        self.assertEqual(len(state), 2)

    def test_tracking_params_collapse_to_one_entry(self):
        state = {}
        sync_new_watch_opportunities(
            state,
            [
                _watch_opportunity(url="https://www.turners.co.nz/x?utm_source=fb"),
                _watch_opportunity(url="https://www.turners.co.nz/x?utm_source=twitter"),
            ],
        )
        self.assertEqual(len(state), 1)

    def test_opportunities_list_itself_is_never_mutated(self):
        state = {}
        opp = _watch_opportunity()
        original_repr = repr(opp)
        sync_new_watch_opportunities(state, [opp])
        self.assertEqual(repr(opp), original_repr)


class TestResolvePursued(unittest.TestCase):
    def test_marks_status_pursued_with_resolved_at(self):
        state = {}
        sync_new_watch_opportunities(state, [_watch_opportunity()])
        entry = resolve_pursued(state, "Turners", "https://www.turners.co.nz/x")
        self.assertEqual(entry["status"], STATUS_PURSUED)
        self.assertIsNotNone(entry["resolved_at"])

    def test_returns_none_for_unknown_listing(self):
        state = {}
        self.assertIsNone(resolve_pursued(state, "Turners", "https://www.turners.co.nz/never-seen"))
        self.assertEqual(state, {})

    def test_pursued_listing_is_never_re_added_by_a_later_scan(self):
        state = {}
        opp = _watch_opportunity()
        sync_new_watch_opportunities(state, [opp])
        resolve_pursued(state, "Turners", "https://www.turners.co.nz/x")

        added = sync_new_watch_opportunities(state, [opp])  # same listing, later scan

        self.assertEqual(added, [])
        key = hunting_make_key("Turners", "https://www.turners.co.nz/x")
        self.assertEqual(state[key]["status"], STATUS_PURSUED)


class TestResolveRejected(unittest.TestCase):
    def test_marks_status_rejected_with_resolved_at(self):
        state = {}
        sync_new_watch_opportunities(state, [_watch_opportunity()])
        entry = resolve_rejected(state, "Turners", "https://www.turners.co.nz/x")
        self.assertEqual(entry["status"], STATUS_REJECTED)
        self.assertIsNotNone(entry["resolved_at"])

    def test_returns_none_for_unknown_listing(self):
        state = {}
        self.assertIsNone(resolve_rejected(state, "Turners", "https://www.turners.co.nz/never-seen"))
        self.assertEqual(state, {})

    def test_rejected_listing_is_never_re_added_by_a_later_scan(self):
        # The exact requirement: "Reject: ... persist the resolution so
        # the same listing does not immediately re-enter as a new pending
        # item on the next scan."
        state = {}
        opp = _watch_opportunity()
        sync_new_watch_opportunities(state, [opp])
        resolve_rejected(state, "Turners", "https://www.turners.co.nz/x")

        added = sync_new_watch_opportunities(state, [opp])  # same listing, later scan

        self.assertEqual(added, [])
        key = hunting_make_key("Turners", "https://www.turners.co.nz/x")
        self.assertEqual(state[key]["status"], STATUS_REJECTED)
        self.assertEqual(len(state), 1)


class TestGetAndActivePendingEntries(unittest.TestCase):
    def test_get_returns_entry_by_source_and_url(self):
        state = {}
        sync_new_watch_opportunities(state, [_watch_opportunity()])
        entry = get(state, "Turners", "https://www.turners.co.nz/x")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["source"], "Turners")

    def test_get_returns_none_when_absent(self):
        self.assertIsNone(get({}, "Turners", "https://www.turners.co.nz/never-seen"))

    def test_active_pending_entries_excludes_resolved(self):
        state = {}
        sync_new_watch_opportunities(
            state,
            [
                _watch_opportunity(url="https://www.turners.co.nz/a"),
                _watch_opportunity(url="https://www.turners.co.nz/b"),
                _watch_opportunity(url="https://www.turners.co.nz/c"),
            ],
        )
        resolve_pursued(state, "Turners", "https://www.turners.co.nz/a")
        resolve_rejected(state, "Turners", "https://www.turners.co.nz/b")

        active = active_pending_entries(state)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["url"], "https://www.turners.co.nz/c")


if __name__ == "__main__":
    unittest.main()
