"""Cross-process guard against two `python main.py --mode discover` runs
executing concurrently.

Nothing before this existed: scanner/dashboard_server.py's own
`_scan_lock`/`_scan_process` pair (an in-process `threading.Lock` plus a
module-level variable) only protects against two clicks hitting the SAME
running dashboard_server.py process. It does nothing if that server is
restarted while a subprocess it already spawned is still alive
(`subprocess.Popen` children are never killed just because their parent
process exits -- no process-group/job-object cleanup is set up anywhere in
this codebase), or if `python main.py --mode discover` is ever run from
anywhere else (a second terminal, a scheduled task) while another one is
already going.

When that happens, two independent OS processes end up writing the SAME
shared files -- `data/scan_progress.json`, `reports/discovery_index.json`,
`reports/deal_queue.html` -- with zero coordination. Reproduced directly
(two real discover-mode runs, ~2.5s apart, against the same files):

- `reports/deal_queue.html` gets regenerated a second time, moments after
  the first, silently replacing already-correct, already-shown results
  with an unrelated second run's -- this is the "results appear correctly,
  then a few seconds later revert" symptom.
- `scanner/discovery_report.py`'s minute-granularity output filenames
  collided outright: the second run's `discovery_<timestamp>.json` write
  silently overwrote the first run's file, leaving `discovery_index.json`
  with two entries (different `opportunity_count`/`decision_counts`) that
  both point at the same now-overwritten file -- the older entry's own
  metadata no longer matches the file it names.
- `data/scan_progress.json` was left in a self-contradictory state
  (`running: false` from one process's completion immediately merged back
  towards `stage: RESEARCH` by the other process's still-in-flight
  progress update, since `scan_progress.update_progress()` only patches
  the keys it's given). The frontend's `pollScanStatus()` stops polling
  for good the first time it observes `running: false` and only renders
  UI for `stage` COMPLETE/FAILED -- so a `running:false`/`stage:RESEARCH`
  combination freezes the panel silently and permanently for that page
  load, with the user never told a second run is even happening.

Also, because both processes independently re-scrape the same
`turners_categories` (Discovery reuses the exact same Turners scrapers as
the legacy pipeline -- see scanner/search/auction_search.py), two
overlapping runs surface many of the same physical listings, contributing
to the separate "duplicate opportunities" symptom.

This module is the fix: an exclusive lock file, acquired atomically with
`os.O_CREAT | os.O_EXCL` (identical semantics on POSIX and Windows -- no
platform-specific PID-liveness check needed), held for the lifetime of one
discover-mode run. A lock older than STALE_SECONDS is treated as abandoned
(the process that held it crashed or was killed without cleaning up) and
reclaimed automatically -- mirroring the stale-scan heuristic the frontend
already uses (`SCAN_STALL_SECONDS` in deal_queue_report.py) rather than
trying to verify PID liveness across platforms.
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "scan.lock")

# Generous vs a realistic multi-minute discovery scan (this project's own
# prior QA notes document real runs taking several minutes) -- long enough
# that a genuinely still-running scan is never mistaken for abandoned,
# short enough that a crashed process doesn't wedge every future scan for
# good.
STALE_SECONDS = 1800


def _read_lock(path: str) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _is_stale(lock_data: Optional[dict], now: float) -> bool:
    started_at = lock_data.get("started_at") if lock_data else None
    if not isinstance(started_at, (int, float)):
        # Missing/corrupt lock content can't be trusted to still be live --
        # treat it as abandoned rather than wedging every future scan.
        return True
    return (now - started_at) > STALE_SECONDS


def is_held(path: str = DEFAULT_PATH) -> bool:
    """Read-only check: is a fresh (non-stale) lock currently held?

    Used by dashboard_server.py to give an immediate, clear 409 before even
    spawning a subprocess that would otherwise just fail to acquire the
    lock itself a moment later."""
    if not os.path.exists(path):
        return False
    return not _is_stale(_read_lock(path), time.time())


def acquire(path: str = DEFAULT_PATH) -> bool:
    """Attempts to take the lock for the current process. Returns True if
    acquired, False if another (non-stale) run already holds it.

    Reclaims a stale lock automatically. If reclaiming races with another
    process doing the same thing, only one of them wins the subsequent
    O_CREAT|O_EXCL open -- the loser correctly gets False back, never a
    false "acquired"."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    if os.path.exists(path) and _is_stale(_read_lock(path), time.time()):
        try:
            os.remove(path)
        except OSError:
            pass  # another process may have already reclaimed/removed it

    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"pid": os.getpid(), "started_at": time.time()}, f)
    return True


def release(path: str = DEFAULT_PATH) -> None:
    """Best-effort release -- safe to call even if this process never held
    the lock (e.g. an early exit before acquire() was reached)."""
    try:
        os.remove(path)
    except OSError:
        pass
