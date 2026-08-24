import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

from scanner import dashboard_server, scan_lock, scan_progress


class _FakeProcess:
    """Stands in for subprocess.Popen in tests -- controllable from the
    test itself instead of actually spawning `python main.py --mode
    discover` (a multi-minute discovery scan requiring live network access
    and API keys neither available nor wanted in a unit test)."""

    def __init__(self):
        self._done = threading.Event()
        self.returncode = None

    def poll(self):
        return self.returncode if self._done.is_set() else None

    def wait(self):
        self._done.wait(timeout=5)
        return self.returncode

    def finish(self, returncode=0):
        self.returncode = returncode
        self._done.set()


class DashboardServerScanEndpointsTest(unittest.TestCase):
    """Exercises POST /api/scan/start and GET /api/scan/status against a
    real ThreadingHTTPServer (the same class scanner/dashboard_server.py
    runs in production), with subprocess spawning mocked out. This is the
    same style unittest.mock recommends for http.server-based code -- a
    real server on an ephemeral port, driven over a real socket, rather
    than trying to unit-test BaseHTTPRequestHandler methods directly
    (they assume a live request/response cycle)."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard_server.HuntingRequestHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        # data/scan_progress.json is real, shared, transient scratch state
        # (see scanner/scan_progress.py's module docstring) -- back it up
        # and restore it after each test so these tests never leave a
        # permanent side effect on the repo, regardless of the fact that
        # scan_progress's module-level functions bind DEFAULT_PATH at
        # scan_progress.py's own import time (so per-test temp-path
        # injection isn't available the way tests/test_hunting_store.py
        # does it for an explicit `path=` argument).
        self._real_path = scan_progress.DEFAULT_PATH
        self._backup = None
        if os.path.exists(self._real_path):
            with open(self._real_path, encoding="utf-8") as f:
                self._backup = f.read()
            os.remove(self._real_path)

        # scan_lock.DEFAULT_PATH is real, shared, cross-process state too
        # (see scanner/scan_lock.py) -- same backup/restore treatment as
        # scan_progress's file above, for the same reason: these tests must
        # never leave a stray lock file behind (which would wedge every
        # future real scan) or clobber one a real scan already holds.
        self._real_lock_path = scan_lock.DEFAULT_PATH
        self._lock_backup = None
        if os.path.exists(self._real_lock_path):
            with open(self._real_lock_path, encoding="utf-8") as f:
                self._lock_backup = f.read()
            os.remove(self._real_lock_path)

        # Reset dashboard_server's module-level scan-tracking state so
        # tests never leak a "running" process into one another.
        dashboard_server._scan_process = None

        self.spawn_patch = mock.patch("scanner.dashboard_server._spawn_scan_process")
        self.mock_spawn = self.spawn_patch.start()
        self.addCleanup(self.spawn_patch.stop)

    def tearDown(self):
        dashboard_server._scan_process = None
        if os.path.exists(self._real_path):
            os.remove(self._real_path)
        if self._backup is not None:
            with open(self._real_path, "w", encoding="utf-8") as f:
                f.write(self._backup)

        if os.path.exists(self._real_lock_path):
            os.remove(self._real_lock_path)
        if self._lock_backup is not None:
            with open(self._real_lock_path, "w", encoding="utf-8") as f:
                f.write(self._lock_backup)

    def _url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def _get(self, path):
        with urllib.request.urlopen(self._url(path), timeout=5) as r:
            return r.status, json.loads(r.read())

    def _post(self, path, body=None):
        data = json.dumps(body or {}).encode("utf-8")
        req = urllib.request.Request(self._url(path), data=data, method="POST",
                                      headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_status_when_no_scan_has_ever_run(self):
        status, body = self._get("/api/scan/status")
        self.assertEqual(status, 200)
        self.assertFalse(body["running"])
        self.assertIsNone(body["stage"])

    def test_status_reflects_real_persisted_progress(self):
        scan_progress.start_progress(queries_total=7)
        status, body = self._get("/api/scan/status")
        self.assertEqual(status, 200)
        self.assertTrue(body["running"])
        self.assertEqual(body["queries_total"], 7)
        self.assertEqual(body["stage"], "SEARCH")

    def test_start_scan_spawns_process_and_returns_200(self):
        fake = _FakeProcess()
        self.mock_spawn.return_value = fake

        status, body = self._post("/api/scan/start")

        self.assertEqual(status, 200)
        self.assertTrue(body["started"])
        self.mock_spawn.assert_called_once()

        fake.finish(0)  # let the watcher thread exit cleanly before teardown

    def test_second_start_rejected_with_409_while_running(self):
        fake = _FakeProcess()
        self.mock_spawn.return_value = fake
        status1, _ = self._post("/api/scan/start")
        self.assertEqual(status1, 200)

        status2, body2 = self._post("/api/scan/start")
        self.assertEqual(status2, 409)
        self.assertIn("already running", body2["error"].lower())
        # Only one subprocess was ever spawned -- the second request must
        # not have started a second one.
        self.mock_spawn.assert_called_once()

        fake.finish(0)

    def test_second_start_rejected_when_cross_process_lock_is_held(self):
        # Regression guard for the "results appear then revert" / duplicate
        # opportunities bug: this server's own in-process _scan_process
        # tracking has no idea a `python main.py --mode discover` process
        # is running -- e.g. left over from before this server was
        # restarted, or started by hand in another terminal -- unless it
        # also checks the cross-process lock file scan_lock.py introduces.
        # Simulates exactly that: _scan_process is None (as if freshly
        # (re)started) but the lock is genuinely held by someone else.
        self.assertTrue(scan_lock.acquire(self._real_lock_path))
        self.assertIsNone(dashboard_server._scan_process)

        status, body = self._post("/api/scan/start")

        self.assertEqual(status, 409)
        self.mock_spawn.assert_not_called()

    def test_start_succeeds_once_the_cross_process_lock_is_released(self):
        scan_lock.acquire(self._real_lock_path)
        status1, _ = self._post("/api/scan/start")
        self.assertEqual(status1, 409)

        scan_lock.release(self._real_lock_path)
        fake = _FakeProcess()
        self.mock_spawn.return_value = fake
        status2, body2 = self._post("/api/scan/start")

        self.assertEqual(status2, 200)
        self.assertTrue(body2["started"])
        fake.finish(0)

    def test_start_succeeds_again_once_previous_scan_finished(self):
        fake1 = _FakeProcess()
        self.mock_spawn.return_value = fake1
        self._post("/api/scan/start")
        fake1.finish(0)

        # Give the background watcher thread a moment to clear
        # dashboard_server._scan_process after fake1.wait() returns.
        for _ in range(50):
            if dashboard_server._scan_process is None:
                break
            time.sleep(0.02)

        fake2 = _FakeProcess()
        self.mock_spawn.return_value = fake2
        status, body = self._post("/api/scan/start")
        self.assertEqual(status, 200)
        self.assertTrue(body["started"])
        self.assertEqual(self.mock_spawn.call_count, 2)

        fake2.finish(0)

    def test_crash_before_fail_progress_is_reconciled_as_failed(self):
        # Simulates main.py's --mode discover branch having called
        # start_progress() but then the interpreter being killed outright
        # before its own except-block could call fail_progress() (e.g. a
        # hard crash, OOM-kill) -- the progress file is left saying
        # running=true forever unless something else notices the process
        # actually died.
        scan_progress.start_progress(queries_total=3)
        fake = _FakeProcess()
        self.mock_spawn.return_value = fake
        self._post("/api/scan/start")

        fake.finish(returncode=1)

        status = None
        for _ in range(50):
            status, body = self._get("/api/scan/status")
            if not body["running"]:
                break
            time.sleep(0.02)

        self.assertFalse(body["running"])
        self.assertEqual(body["stage"], "FAILED")
        self.assertIn("exit code 1", body["error"])

    def test_crash_reconciliation_does_not_overwrite_an_already_recorded_failure(self):
        # If main.py's own except-block DID get to call fail_progress()
        # with a real, specific error before the process exited, the
        # generic "exited unexpectedly" reconciliation message must never
        # clobber it.
        scan_progress.start_progress(queries_total=3)
        scan_progress.fail_progress("Discovery scan failed: a specific real reason")
        fake = _FakeProcess()
        self.mock_spawn.return_value = fake
        self._post("/api/scan/start")

        fake.finish(returncode=1)
        time.sleep(0.1)  # let the watcher thread's reconciliation check run

        status, body = self._get("/api/scan/status")
        self.assertEqual(body["error"], "Discovery scan failed: a specific real reason")

    def test_responses_are_never_cached_by_the_browser(self):
        # Regression guard for the Command Centre's "results appear then
        # revert" bug: with no Cache-Control header (the previous
        # behaviour), a browser is free to serve a cached, pre-regeneration
        # copy of deal_queue.html on a later fetch of the same URL -- a
        # second tab, a back/forward navigation, or a backgrounded tab
        # being silently reloaded -- with no network round-trip at all,
        # which looks exactly like freshly-regenerated results reverting to
        # a prior run's. Every response this server sends, the JSON status
        # endpoint and the static dashboard file alike, must carry
        # Cache-Control: no-store so that can never happen.
        with urllib.request.urlopen(self._url("/api/scan/status"), timeout=5) as r:
            self.assertEqual(r.headers.get("Cache-Control"), "no-store")
            r.read()  # drain fully so the server thread doesn't hit a
            # BrokenPipeError writing to a socket this `with` block already
            # closed -- harmless to the assertion above, but noisy in test
            # output otherwise.
        with urllib.request.urlopen(self._url("/deal_queue.html"), timeout=5) as r:
            self.assertEqual(r.headers.get("Cache-Control"), "no-store")
            r.read()

    def test_hunting_endpoint_unaffected_by_scan_routing_changes(self):
        # Regression guard: adding the /api/scan/* routes to do_GET/do_POST
        # must not disturb the pre-existing Hunting routes they sit
        # alongside.
        status, body = self._get("/api/hunting")
        self.assertEqual(status, 200)
        self.assertIn("hunting", body)


if __name__ == "__main__":
    unittest.main()
