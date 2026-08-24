import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import tempfile
import time
import unittest

from scanner import scan_lock


class TestAcquireRelease(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.path = os.path.join(self.tmpdir.name, "scan.lock")

    def test_first_acquire_succeeds(self):
        self.assertTrue(scan_lock.acquire(self.path))
        self.assertTrue(os.path.exists(self.path))

    def test_second_acquire_fails_while_first_still_held(self):
        # This is the exact real-world scenario this module exists to
        # prevent: a second `python main.py --mode discover` process
        # (started by hand, by a restarted dashboard_server.py, or by a
        # second click) must never be able to acquire the lock while a
        # first one already holds it.
        self.assertTrue(scan_lock.acquire(self.path))
        self.assertFalse(scan_lock.acquire(self.path))

    def test_acquire_succeeds_again_after_release(self):
        self.assertTrue(scan_lock.acquire(self.path))
        scan_lock.release(self.path)
        self.assertTrue(scan_lock.acquire(self.path))

    def test_release_when_never_acquired_is_a_safe_no_op(self):
        scan_lock.release(self.path)  # must not raise
        self.assertFalse(os.path.exists(self.path))

    def test_lock_file_records_pid_and_started_at(self):
        scan_lock.acquire(self.path)
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["pid"], os.getpid())
        self.assertIsInstance(data["started_at"], (int, float))

    def test_creates_parent_directory_if_missing(self):
        nested = os.path.join(self.tmpdir.name, "nested", "dir", "scan.lock")
        self.assertTrue(scan_lock.acquire(nested))
        self.assertTrue(os.path.exists(nested))


class TestIsHeld(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.path = os.path.join(self.tmpdir.name, "scan.lock")

    def test_false_when_no_lock_file_exists(self):
        self.assertFalse(scan_lock.is_held(self.path))

    def test_true_while_a_fresh_lock_is_held(self):
        scan_lock.acquire(self.path)
        self.assertTrue(scan_lock.is_held(self.path))

    def test_false_after_release(self):
        scan_lock.acquire(self.path)
        scan_lock.release(self.path)
        self.assertFalse(scan_lock.is_held(self.path))

    def test_is_held_never_creates_or_mutates_the_lock_file(self):
        # A read-only peek (dashboard_server.py calls this before deciding
        # whether to even spawn a subprocess) must never itself take or
        # disturb the lock.
        scan_lock.is_held(self.path)
        self.assertFalse(os.path.exists(self.path))


class TestStaleLockReclaim(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.path = os.path.join(self.tmpdir.name, "scan.lock")

    def _write_lock(self, started_at):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"pid": 999999, "started_at": started_at}, f)

    def test_stale_lock_is_not_held(self):
        self._write_lock(time.time() - scan_lock.STALE_SECONDS - 60)
        self.assertFalse(scan_lock.is_held(self.path))

    def test_fresh_lock_is_held(self):
        self._write_lock(time.time() - 5)
        self.assertTrue(scan_lock.is_held(self.path))

    def test_acquire_reclaims_a_stale_lock(self):
        # A crashed/killed process (interpreter killed outright, e.g.
        # OOM-kill) never gets to call release() -- a lock this old must
        # not wedge every future scan permanently.
        self._write_lock(time.time() - scan_lock.STALE_SECONDS - 60)
        self.assertTrue(scan_lock.acquire(self.path))

    def test_acquire_does_not_reclaim_a_fresh_lock(self):
        self._write_lock(time.time() - 5)
        self.assertFalse(scan_lock.acquire(self.path))

    def test_corrupt_lock_file_is_treated_as_stale(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        self.assertFalse(scan_lock.is_held(self.path))
        self.assertTrue(scan_lock.acquire(self.path))


if __name__ == "__main__":
    unittest.main()
