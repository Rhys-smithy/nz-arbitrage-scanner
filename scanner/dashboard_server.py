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

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")
DEFAULT_PORT = 8765

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
        super().do_GET()

    def do_POST(self):
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
