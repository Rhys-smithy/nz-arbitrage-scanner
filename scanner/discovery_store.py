"""Phase 3: freshness tracking for discovered (search-based) listings.

Deliberately separate from scanner/store.py's existing seen.json (which
Phase 2's auction pipeline uses for its own dedup logic) -- Phase 3 must
not modify that behaviour. This tracks first_seen/last_seen per canonical
URL so discovery can prioritise newly-appeared listings without touching
the auction pipeline's state file.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from scanner.search.util import canonicalize_url

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "discovered.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_discovered(path: str = DEFAULT_PATH) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_discovered(discovered: dict, path: str = DEFAULT_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(discovered, f, indent=2, sort_keys=True)


def record_sightings(results: list, discovered: dict) -> dict:
    """Update `discovered` in place with first_seen/last_seen/source for each
    result (keyed by canonical URL). Returns the set of canonical URLs that
    are newly seen this run (useful for prioritising fresh listings)."""
    now = _now()
    new_urls = set()
    for r in results:
        key = canonicalize_url(r.url)
        if not key:
            continue
        if key not in discovered:
            discovered[key] = {"first_seen": now, "last_seen": now, "source": r.source, "url": r.url}
            new_urls.add(key)
        else:
            discovered[key]["last_seen"] = now
    return new_urls
