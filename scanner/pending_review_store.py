"""Pending Review queue persistence: a durable human-review workflow layer
over WATCH opportunities the discovery pipeline finds.

Problem this solves
--------------------
``scanner/deal_queue_report.py`` only ever renders the LATEST persisted
discovery payload (``reports/discovery_index.json`` -> newest
``discovery_<timestamp>.json``). A WATCH opportunity found today can
simply not appear in a later run -- better/worse listings crowd it out of
``max_research_items``, the listing sells or closes, a transient scrape
hiccup, or the daily ``.github/workflows/scan.yml`` cron (or a manual
"Run Scan" click) just finds a different set of candidates -- and today
that means it silently vanishes from the dashboard the moment any newer
scan completes, before Rhys ever reviewed it.

This module is a separate, durable queue, deliberately outside the
scanner pipeline: when a scan finds a new WATCH opportunity, a small
snapshot entry is added here (``main.py``'s ``--mode discover`` branch
owns the write -- see its own comments -- mirroring how it already owns
``scanner/scan_progress.py`` writes there). The entry persists regardless
of what later scans find, until Rhys explicitly resolves it via one of
the two terminal actions:

- Pursue: also stars the same listing into the existing Hunting workflow
  (``scanner/hunting_store.py``), then marks this record resolved so it
  is never re-added.
- Reject: marks this record resolved (no Hunting side effect), so it is
  never re-added.

Both actions are composed by ``scanner/dashboard_server.py`` (the one
process that writes ``data/pending_review_state.json`` and
``data/hunting_state.json``) as two explicit calls -- one into this
module, one into ``scanner/hunting_store.py`` for Pursue -- rather than
this module reaching into the Hunting store itself. Each store keeps its
own file format and its own single responsibility.

Identity: reuses ``scanner.hunting_store.make_key()`` -- itself
``source + canonicalize_url()`` (see ``scanner/search/util.py``) -- rather
than inventing a second identity system. This is not just DRY: it also
means a Pursue transition is a trivial 1:1 key match into
``hunting_store``'s own dict, with no re-derivation, since a pending
review key and the Hunting key for the same listing are always identical.

Deliberately separate from every scanner-generated file (same list as
``scanner/hunting_store.py``'s own docstring: ``scanner/report.py``'s
CSV, ``scanner/discovery_report.py``'s ``discovery_*.json``,
``scanner/store.py``'s ``seen.json``, ``scanner/discovery_store.py``'s
``discovered.json``) -- none of those are read or written here, and this
module is never imported by the scanner/discovery pipelines themselves
(``scanner/discover.py`` is untouched by this feature; only ``main.py``'s
orchestration layer calls this module, after ``run_discovery()`` has
already returned and persisted its own output). It is also separate from
``data/hunting_state.json`` itself -- this module never reads or writes
that file directly.

Scope is deliberately minimal, matching ``hunting_store.py``'s own stated
approach: three statuses (pending/pursued/rejected), a small display
snapshot (title/source/url/price/flip_score/verification_status) captured
at add-time so a pending item can still be shown after it drops out of
the latest scan, and a ``last_seen_at`` timestamp refreshed on repeat
sightings while still pending. No notes, no priority, no notifications --
those would be later, additive extensions of this same record, not a
reason to build more schema now.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Iterable, Optional

from scanner.hunting_store import make_key

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "pending_review_state.json")

STATUS_PENDING = "pending"
STATUS_PURSUED = "pursued"
STATUS_REJECTED = "rejected"

# Guards read-modify-write sequences against concurrent requests when this
# module is driven by scanner/dashboard_server.py's threaded HTTP server --
# same rationale as scanner/hunting_store.py's own _LOCK. Not needed for
# main.py's single-shot scan-time sync() call, but cheap and correct
# either way.
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_pending_review_state(path: str = DEFAULT_PATH) -> dict:
    """Returns the persisted pending-review dict, or {} if the file is
    missing or corrupt -- mirrors scanner.hunting_store.load_hunting_state()'s
    failure handling exactly, so a bad file never crashes a scan or the
    local server, it just behaves like "nothing pending yet"."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_pending_review_state(state: dict, path: str = DEFAULT_PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def get(state: dict, source: str, url: str) -> Optional[dict]:
    return state.get(make_key(source, url))


def sync_new_watch_opportunities(state: dict, opportunities: Iterable) -> list:
    """Adds a pending-review entry for every WATCH opportunity in this
    run's already-scored, already-decided ``opportunities`` (the exact
    list ``scanner.discover.run_discovery()`` returned -- read-only here,
    never mutated, and never re-scored/re-decided).

    A listing whose key already has ANY record in `state` -- pending,
    pursued, or rejected -- is left completely untouched: this never
    duplicates an already-pending item and never resurrects one Rhys
    already resolved (Pursue or Reject). The one exception is
    ``last_seen_at``, refreshed on a still-pending record's repeat
    sighting -- a display-only freshness signal, not a new record and not
    a change to status/found_at/resolved_at.

    Only ``decision == "WATCH"`` opportunities are considered -- BUY,
    PROFITABLE BUT CAPITAL RISK, and PASS are out of this feature's scope
    entirely, per the task this module was built for.

    Returns the list of newly-created entries (dicts, already inserted
    into `state`) so callers can log/report what changed.
    """
    added = []
    for o in opportunities:
        if getattr(o, "decision", None) != "WATCH":
            continue
        source = getattr(o, "source", None)
        url = getattr(o, "url", None)
        if not source or not url:
            continue
        key = make_key(source, url)
        if key in state:
            if state[key].get("status") == STATUS_PENDING:
                state[key]["last_seen_at"] = _now()
            continue
        now = _now()
        entry = {
            "source": source,
            "url": url,
            "title": getattr(o, "title", None),
            "current_price": getattr(o, "current_price", None),
            "buy_now_price": getattr(o, "buy_now_price", None),
            "flip_score": getattr(o, "flip_score", None),
            "verification_status": getattr(o, "verification_status", None),
            "status": STATUS_PENDING,
            "found_at": now,
            "last_seen_at": now,
            "resolved_at": None,
        }
        state[key] = entry
        added.append(entry)
    return added


def resolve_pursued(state: dict, source: str, url: str) -> Optional[dict]:
    """Marks a pending-review record Pursued (terminal -- never re-added
    by a later sync_new_watch_opportunities() call for the same key).

    Starring the listing into scanner/hunting_store.py's Hunting workflow
    is the caller's responsibility (see scanner/dashboard_server.py's
    POST /api/pending_review/pursue) -- this function only ever touches
    this module's own store. Returns None (no-op) if the listing has no
    pending-review record at all, mirroring
    scanner.hunting_store.update_notes()'s same "never implicitly create
    one" rule.
    """
    key = make_key(source, url)
    if key not in state:
        return None
    state[key]["status"] = STATUS_PURSUED
    state[key]["resolved_at"] = _now()
    return state[key]


def resolve_rejected(state: dict, source: str, url: str) -> Optional[dict]:
    """Marks a pending-review record Rejected (terminal -- never re-added
    by a later sync_new_watch_opportunities() call for the same key, which
    is exactly what prevents an immediately-rejected listing from
    reappearing as a new pending item on the very next scan). Returns None
    (no-op) if the listing has no pending-review record at all.
    """
    key = make_key(source, url)
    if key not in state:
        return None
    state[key]["status"] = STATUS_REJECTED
    state[key]["resolved_at"] = _now()
    return state[key]


def active_pending_entries(state: dict) -> list:
    """Convenience filter: every record still awaiting a decision, newest
    first. Not used by the HTTP API (which -- like scanner/hunting_store.py's
    own /api/hunting -- returns the whole state dict verbatim and lets the
    dashboard's client-side JS filter by status, exactly mirroring the
    existing Hunting embedding pattern), but kept here since main.py's own
    log line and tests both want "how many are actually pending" without
    duplicating this filter.
    """
    return sorted(
        (e for e in state.values() if isinstance(e, dict) and e.get("status") == STATUS_PENDING),
        key=lambda e: e.get("found_at") or "",
        reverse=True,
    )
