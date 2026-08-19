"""Minimal local write path for the Hunting workflow.

``reports/deal_queue.html`` is (deliberately, per its own module
docstring in scanner/deal_queue_report.py) a single generated static file
with no server behind it, opened via ``file://``. A ``file://`` page has
no channel back to disk -- it cannot fetch()/POST to itself, and nothing
is listening even if it could. Starring a listing therefore cannot be a
pure client-side feature; something has to run locally and own the write.

This is the smallest thing that can own it: Python's *standard library*
``http.server``, nothing else. No third-party dependency, no web
framework (Flask/Django/etc.), no database, no background/always-on
service -- start it when you want to star things, stop it (Ctrl+C) when
you're done. It does exactly two jobs:

1. Serves ``reports/`` as static files, so opening
   ``http://127.0.0.1:8765/deal_queue.html`` (instead of ``file://...``)
   gives the page a real same-origin fetch()/POST target instead of none.
2. Exposes a tiny JSON API backed directly by ``scanner/hunting_store.py``
   -- the exact same store ``scanner/deal_queue_report.py`` reads
   (read-only) when it embeds a snapshot of hunting state at generation
   time. This process is the only thing that ever writes
   ``data/hunting_state.json``.

It also owns the Command Centre's "Run Scan" on-demand-scan workflow, for
the same reason: a click needs somewhere to start a scan and somewhere to
poll live progress from, and this is already the one long-lived local
process for exactly that kind of thing. POST /api/scan/start spawns
``python main.py --mode discover`` as its own OS subprocess (never inside
the request-handling thread -- a discovery scan takes minutes, and this
server must keep answering every other request the whole time) and
rejects a second concurrent start with 409. GET /api/scan/status reads
back whatever ``scanner/scan_progress.py`` -- written to by the scan
subprocess itself, not by this server -- currently has in
``data/scan_progress.json``. This server never computes scan progress
itself, only relays it.

Nothing here touches scanner opportunity data: no discovery_*.json, no
opportunities_*.csv/xlsx, no config.json is ever read or written by this
module.

Usage::

    python -m scanner.dashboard_server
    # then open the printed URL in a browser

An alternative considered and rejected: the browser's File System Access
API (``showSaveFilePicker``/``showDirectoryPicker``) can, in Chrome, write
a local file directly from a ``file://`` page with no server at all.
It was tested and confirmed to be *technically* available on
``file://`` pages, but it's Chrome/Edge-only (no path for Trade Me-style
mobile viewing of the dashboard), requires a persisted per-browser
permission grant that has to be re-established per profile, and -- most
concretely -- it cannot be driven by any browser-automation tooling
(the native OS picker blocks scripted interaction), which would have made
this feature's own regression testing impossible going forward. A tiny
local HTTP helper is cross-browser, requires no permission dance, and is
fully scriptable for tests.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from scanner.hunting_store import (
    DEFAULT_PATH,
    load_hunting_state,
    make_key,
    save_hunting_state,
    star,
    unstar,
    update_notes,
    update_target_offer,
)
from scanner import scan_progress

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
DEFAULT_PORT = 8765

# ---------------------------------------------------------------------------
# On-demand scan ("Run Scan" in the Command Centre).
#
# The scan itself (python main.py --mode discover) is a completely separate
# OS process from this HTTP server -- it must be, since a single discovery
# scan takes minutes and this server has to keep answering GET /api/hunting
# and GET /api/scan/status requests the whole time. `_scan_process` /
# `_scan_lock` below track at most one such subprocess; a second
# POST /api/scan/start while one is already running is rejected with 409
# rather than ever running two scans concurrently against the same
# data/discovered.json, data/search_stats.json, and reports/ files.
# ---------------------------------------------------------------------------
_scan_lock = threading.Lock()
_scan_process: Optional[subprocess.Popen] = None


def _spawn_scan_process() -> subprocess.Popen:
    """Starts `python main.py --mode discover` as a detached subprocess.
    Pulled out as its own function (rather than inlined below) so tests
    can monkeypatch it with a fake, controllable process object instead of
    actually spawning a multi-minute discovery scan."""
    return subprocess.Popen(
        [sys.executable, "main.py", "--mode", "discover"],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _watch_scan_process(proc: subprocess.Popen) -> None:
    """Runs in a background daemon thread for the lifetime of one scan.
    Blocks on proc.wait() (never in the request-handling thread), then:

    1. Clears `_scan_process` so a new scan can be started once this one
       is truly finished, independent of whether anyone is polling status.
    2. Reconciles data/scan_progress.json if the subprocess exited non-zero
       but the progress file still says running=true -- this means
       main.py's own try/except (scanner/scan_progress.fail_progress(),
       see main.py's --mode discover branch) never got a chance to run,
       e.g. the interpreter crashed outright or was killed. Without this,
       a hard crash would leave the dashboard showing a scan that looks
       like it's still running forever.
    """
    returncode = proc.wait()
    global _scan_process
    with _scan_lock:
        _scan_process = None
    if returncode != 0:
        state = scan_progress.load_progress()
        if state.get("running"):
            scan_progress.fail_progress(
                f"Scan process exited unexpectedly (exit code {returncode})."
            )


def start_scan() -> bool:
    """Starts a discovery scan if none is currently running.

    Returns True if a new scan was started, False if one was already
    running (the caller -- do_POST below -- returns 409 in that case).
    Never blocks on the scan itself: only the (near-instant) subprocess
    spawn happens under the lock; the actual multi-minute scan runs
    entirely in the child process, and _watch_scan_process() above runs in
    its own background thread, not this one.
    """
    global _scan_process
    with _scan_lock:
        if _scan_process is not None and _scan_process.poll() is None:
            return False
        _scan_process = _spawn_scan_process()
        proc = _scan_process
    threading.Thread(target=_watch_scan_process, args=(proc,), daemon=True).start()
    return True

# Serialises every read-modify-write against data/hunting_state.json
# across request threads (ThreadingHTTPServer spawns one thread per
# connection). scanner/hunting_store.py's own lock covers callers within
# one process; this is that lock, held for the load->mutate->save
# sequence so two near-simultaneous clicks (e.g. a double-click) can't
# race and drop one of them.
_WRITE_LOCK = threading.Lock()

_API_ROUTES = (
    "/api/hunting/star",
    "/api/hunting/unstar",
    "/api/hunting/notes",
    "/api/hunting/target_offer",
)


class HuntingRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=REPORTS_DIR, **kwargs)

    def log_message(self, fmt, *args):  # quieter, clearly-tagged logging
        print("[dashboard_server]", fmt % args)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> Optional[dict]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def do_GET(self):
        if self.path == "/api/hunting":
            state = load_hunting_state()
            self._send_json(200, {"hunting": state})
            return
        if self.path == "/api/scan/status":
            self._send_json(200, scan_progress.load_progress())
            return
        super().do_GET()

    def do_POST(self):
        if self.path == "/api/scan/start":
            started = start_scan()
            if not started:
                self._send_json(409, {"error": "Scan already running", "status": scan_progress.load_progress()})
                return
            self._send_json(200, {"started": True, "status": scan_progress.load_progress()})
            return

        if self.path not in _API_ROUTES:
            self._send_json(404, {"error": "not found"})
            return

        body = self._read_json_body()
        if not body or not body.get("source") or not body.get("url"):
            self._send_json(400, {"error": "source and url are required"})
            return

        source = body["source"]
        url = body["url"]

        with _WRITE_LOCK:
            state = load_hunting_state()

            if self.path == "/api/hunting/star":
                entry = star(
                    state,
                    source,
                    url,
                    notes=body.get("notes"),
                    target_offer_override=body.get("target_offer_override"),
                )
                save_hunting_state(state)
                self._send_json(200, {"key": make_key(source, url), "entry": entry})
                return

            if self.path == "/api/hunting/unstar":
                key = make_key(source, url)
                removed = unstar(state, source, url)
                save_hunting_state(state)
                self._send_json(200, {"key": key, "removed": removed})
                return

            if self.path == "/api/hunting/notes":
                entry = update_notes(state, source, url, body.get("notes", ""))
                if entry is None:
                    self._send_json(404, {"error": "not currently hunted"})
                    return
                save_hunting_state(state)
                self._send_json(200, {"entry": entry})
                return

            if self.path == "/api/hunting/target_offer":
                entry = update_target_offer(state, source, url, body.get("target_offer_override"))
                if entry is None:
                    self._send_json(404, {"error": "not currently hunted"})
                    return
                save_hunting_state(state)
                self._send_json(200, {"entry": entry})
                return


def run(port: int = DEFAULT_PORT) -> None:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), HuntingRequestHandler)
    url = f"http://127.0.0.1:{port}/deal_queue.html"
    print(f"[dashboard_server] serving {os.path.abspath(REPORTS_DIR)}")
    print(f"[dashboard_server] open {url}")
    print(f"[dashboard_server] hunting state file: {os.path.abspath(DEFAULT_PATH)}")
    print("[dashboard_server] Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Local dashboard server (enables Hunting persistence)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    run(port=args.port)
