"""Live progress persistence for on-demand discovery scans (the Command
Centre's "Run Scan" workflow).

Modeled directly on scanner/hunting_store.py's persistence pattern (flat
JSON dict, safe handling of a missing/corrupt file, stdlib only, no
database), with one addition: the write here is atomic (tempfile in the
same directory + os.replace()), because unlike hunting_state.json -- which
is written once per user click and read once per page load -- this file is
written repeatedly by a running scan subprocess while the dashboard polls
it roughly once a second from a *different* process. A reader must never
be able to observe a half-written file.

Distinct from every other persisted file in this repo:

- data/hunting_state.json (scanner/hunting_store.py): user-authored,
  permanent workflow state (starred/notes/target offer).
- reports/discovery_<ts>.json (scanner/discovery_report.py): scanner-
  authored, permanent opportunity results.
- data/scan_progress.json (this module): transient, per-run scratch state
  describing whatever scan is currently running or most recently
  finished/failed. Safe to delete at any time. Nothing recomputes,
  reinterprets, or persists business/valuation/scoring data here -- only
  counts that scanner/discover.py and main.py already have in hand at
  each real progress boundary.

This module owns the *shape* of the progress dict and how it's
loaded/saved. It does not know anything about the discovery pipeline
itself -- scanner/discover.py and main.py call start_progress()/
update_progress()/complete_progress()/fail_progress() at points that
already exist in their own control flow.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from typing import Optional

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "scan_progress.json")

STAGE_SEARCH = "SEARCH"
STAGE_VALIDATION = "VALIDATION"
STAGE_RESEARCH = "RESEARCH"
STAGE_COMPLETE = "COMPLETE"
STAGE_FAILED = "FAILED"

# The three real, sequential pipeline stages this module tracks
# individually. COMPLETE/FAILED are terminal states, not stages with their
# own stage_status entry -- see _fresh_stage_status().
_TRACKED_STAGES = (STAGE_SEARCH, STAGE_VALIDATION, STAGE_RESEARCH)

# Guards read-modify-write sequences within one process (mirrors
# hunting_store.py's _LOCK). Not a cross-process file lock -- there is
# only ever one scan subprocess writing this file at a time (see
# scanner/dashboard_server.py's start_scan()), and the dashboard server
# process only ever reads it.
_LOCK = threading.Lock()


def _now() -> float:
    return time.time()


def _fresh_stage_status(active: str) -> dict:
    status = {}
    seen_active = False
    for stage in _TRACKED_STAGES:
        if stage == active:
            status[stage] = "active"
            seen_active = True
        elif seen_active:
            status[stage] = "pending"
        else:
            status[stage] = "done"
    return status


def _empty_state() -> dict:
    """The "no scan has ever run" / file-missing-or-corrupt shape. Every
    key the dashboard's GET /api/scan/status can return is present here so
    a UI never has to guess at a key that might be absent."""
    return {
        "running": False,
        "stage": None,
        "stage_status": {},
        "started_at": None,
        "updated_at": None,
        "heartbeat": None,
        "elapsed_seconds": None,
        "queries_completed": 0,
        "queries_total": 0,
        "raw_results": 0,
        "unique_results": 0,
        "candidates": 0,
        "verified": 0,
        "research_completed": 0,
        "research_total": 0,
        "decision_counts": {},
        "error": None,
        "completed_at": None,
    }


def load_progress(path: str = DEFAULT_PATH) -> dict:
    """Returns the persisted progress dict, or the "no scan" state if the
    file is missing or corrupt -- mirrors hunting_store.load_hunting_
    state()'s failure handling exactly, so a bad or mid-write file can
    never crash the dashboard server or a scan subprocess; it just reads
    back as "nothing to show"."""
    if not os.path.exists(path):
        return _empty_state()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _empty_state()
    if not isinstance(data, dict):
        return _empty_state()
    # Backfill any keys an older/partial write might be missing rather than
    # making every caller defend against a sparse dict.
    merged = _empty_state()
    merged.update(data)
    return merged


def save_progress(state: dict, path: str = DEFAULT_PATH) -> None:
    """Atomic write: write to a temp file in the same directory, then
    os.replace(). Unlike hunting_store.save_hunting_state()'s plain write
    (fine there -- one click, one write, one subsequent page load), this
    file is polled roughly once a second from a different process than the
    one writing it, so a reader must never observe a half-written file."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".scan_progress_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def start_progress(queries_total: int = 0, path: str = DEFAULT_PATH) -> dict:
    """Resets progress to a fresh running state at the start of a scan.
    Always overwrites whatever was there before (a previous run's
    finished/failed state, or nothing) -- this file only ever tracks the
    single current/most-recent scan, never a history."""
    now = _now()
    state = _empty_state()
    state.update({
        "running": True,
        "stage": STAGE_SEARCH,
        "stage_status": _fresh_stage_status(STAGE_SEARCH),
        "started_at": now,
        "updated_at": now,
        "heartbeat": now,
        "elapsed_seconds": 0.0,
        "queries_total": queries_total,
    })
    with _LOCK:
        save_progress(state, path)
    return state


def update_progress(patch: dict, path: str = DEFAULT_PATH) -> dict:
    """Merges `patch` onto whatever's currently persisted, refreshes
    updated_at/heartbeat/elapsed_seconds, and saves. This is the one
    function scanner/discover.py calls at each real progress boundary --
    callers never hand-manage the full state dict or recompute elapsed
    time themselves.

    If called before start_progress() ran this process (shouldn't happen
    in production -- main.py always calls start_progress() first -- but
    keeps this module safe to unit-test in isolation), seeds a fresh
    running state first rather than merging onto a None started_at.
    """
    with _LOCK:
        state = load_progress(path)
        if state.get("started_at") is None:
            now = _now()
            state = _empty_state()
            state.update({
                "running": True,
                "stage": STAGE_SEARCH,
                "stage_status": _fresh_stage_status(STAGE_SEARCH),
                "started_at": now,
            })
        state.update(patch)
        now = _now()
        state["updated_at"] = now
        state["heartbeat"] = now
        if state.get("started_at") is not None:
            state["elapsed_seconds"] = round(now - state["started_at"], 1)
        save_progress(state, path)
        return state


def complete_progress(decision_counts: Optional[dict] = None, path: str = DEFAULT_PATH) -> dict:
    """Marks the scan finished successfully. Called by main.py once the
    Deal Queue view has actually been regenerated from this run's results
    (not by scanner/discover.py itself -- run_discovery() finishing is not
    the same moment as the dashboard having something new to show; see
    main.py's --mode discover branch)."""
    done_status = {stage: "done" for stage in _TRACKED_STAGES}
    return update_progress(
        {
            "running": False,
            "stage": STAGE_COMPLETE,
            "stage_status": done_status,
            "decision_counts": dict(decision_counts or {}),
            "completed_at": _now(),
        },
        path,
    )


def fail_progress(error: str, path: str = DEFAULT_PATH) -> dict:
    """Marks the scan failed. Deliberately only patches running/stage/
    error/completed_at -- update_progress() merges onto whatever stage_
    status/counters were already recorded, so a failure preserves exactly
    how far the scan actually got instead of resetting to a blank slate."""
    return update_progress(
        {"running": False, "stage": STAGE_FAILED, "error": str(error), "completed_at": _now()},
        path,
    )
