"""Hunting workflow persistence: user-authored "keep tracking this" state.

Deliberately separate from every scanner-generated file (scanner/report.py's
CSV, scanner/discovery_report.py's discovery_*.json, scanner/store.py's
seen.json, scanner/discovery_store.py's discovered.json) -- none of those
are read or written here, and this module is never imported by the
scanner/discovery pipelines. Scanner opportunity/valuation data stays
authoritative and untouched; this is the one place personal workflow
state (star, notes, a target-offer override) lives.

Modeled directly on scanner/discovery_store.py's existing pattern: a flat
JSON dict, atomic load/save, corrupt-or-missing file -> empty dict rather
than raising. Keyed by source + canonicalize_url() -- the same
canonicalisation scanner/discovery_store.py already uses for its own
cross-run identity (see scanner/search/util.py) -- rather than inventing a
new identifier. Source is included in the key because canonical URL alone
is not guaranteed unique across sources in principle, even though in
practice every scraper only ever emits its own domain's URLs.

Scope is deliberately minimal (Hunting only, per the current roadmap
stage): status, starred_at, notes, target_offer_override. No
Purchased/Sold fields, no price history, no notifications -- those are
later, additive extensions of this same record (see the project's
persistence audit), not a reason to build more schema now.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Optional

from scanner.search.util import canonicalize_url

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "hunting_state.json")

STATUS_HUNTING = "hunting"

# Guards read-modify-write sequences against concurrent requests when this
# module is driven by scanner/dashboard_server.py's threaded HTTP server.
# Not needed for single-shot CLI/script use, but cheap and correct either
# way -- a plain in-process lock, not a cross-process file lock, since
# there is only ever one local server process for this workflow.
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_key(source: str, url: str) -> str:
    """Stable identity for a listing: source + canonical URL. Reuses
    scanner.search.util.canonicalize_url() -- the exact function
    scanner/discovery_store.py already relies on for cross-run listing
    identity -- rather than a second, possibly-inconsistent normalisation."""
    return f"{(source or '').strip()}|{canonicalize_url(url or '')}"


def load_hunting_state(path: str = DEFAULT_PATH) -> dict:
    """Returns the persisted hunting-state dict, or {} if the file is
    missing or corrupt -- mirrors discovery_store.load_discovered()'s
    failure handling exactly, so a bad file never crashes report
    generation or the local server, it just behaves like "nothing hunted
    yet"."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_hunting_state(state: dict, path: str = DEFAULT_PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def get(state: dict, source: str, url: str) -> Optional[dict]:
    return state.get(make_key(source, url))


def star(
    state: dict,
    source: str,
    url: str,
    notes: Optional[str] = None,
    target_offer_override: Optional[float] = None,
) -> dict:
    """Marks a listing as Hunting (idempotent).

    Re-starring an already-hunted listing preserves its original
    starred_at rather than resetting it, and only overwrites notes /
    target_offer_override when the caller actually passes a non-None
    value -- so re-starring (e.g. clicking the star again after a page
    reload raced the click) never silently wipes an existing note or
    override.
    """
    key = make_key(source, url)
    entry = dict(state.get(key, {}))
    entry["source"] = source
    entry["url"] = url
    entry["status"] = STATUS_HUNTING
    entry.setdefault("starred_at", _now())
    entry.setdefault("notes", "")
    entry.setdefault("target_offer_override", None)
    if notes is not None:
        entry["notes"] = notes
    if target_offer_override is not None:
        entry["target_offer_override"] = target_offer_override
    state[key] = entry
    return entry


def unstar(state: dict, source: str, url: str) -> bool:
    """Removes a listing's hunting record entirely.

    There is no "unhunted" tombstone status yet -- Purchased/Sold aren't
    implemented, so there is nothing downstream that needs to distinguish
    "never hunted" from "hunted, then un-hunted". Returns True only if a
    record actually existed and was removed.
    """
    key = make_key(source, url)
    return state.pop(key, None) is not None


def update_notes(state: dict, source: str, url: str, notes: str) -> Optional[dict]:
    """Updates notes on an existing hunting record.

    Returns None (no-op) if the listing isn't currently hunted -- notes
    only make sense attached to an active hunting record, so this never
    implicitly creates one.
    """
    key = make_key(source, url)
    if key not in state:
        return None
    state[key]["notes"] = notes
    return state[key]


def update_target_offer(
    state: dict, source: str, url: str, target_offer_override: Optional[float]
) -> Optional[dict]:
    """Updates the user's own target-offer override on an existing hunting
    record.

    Deliberately separate from scanner.models.Opportunity.max_buy_price --
    that field is the scanner's own computed figure and is never read or
    written by this module. Returns None (no-op) if the listing isn't
    currently hunted.
    """
    key = make_key(source, url)
    if key not in state:
        return None
    state[key]["target_offer_override"] = target_offer_override
    return state[key]
