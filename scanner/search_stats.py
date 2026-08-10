"""Phase 3 section 17: search-strategy statistics (no ML -- just counting).

Tracks, per bargain-signal "concept" (bundle/lot/moving house/etc, from
config["query_generation"]["concepts"]), how many opportunities it
surfaced and how many turned out profitable (decision == BUY or
PROFITABLE BUT CAPITAL RISK). Persisted to data/search_stats.json so it
accumulates across runs. Purely descriptive today -- future phases can
use this to bias query generation toward historically useful concepts.
"""
from __future__ import annotations

import json
import os

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "search_stats.json")

_PROFITABLE_DECISIONS = {"BUY", "PROFITABLE BUT CAPITAL RISK"}


def load_stats(path: str = DEFAULT_PATH) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_stats(stats: dict, path: str = DEFAULT_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(stats, f, indent=2, sort_keys=True)


def record_query_concept_result(stats: dict, concept: str, decision: str) -> dict:
    """concept: the bargain-signal word/phrase used in the query that found
    this opportunity (e.g. "bundle"). decision: the opportunity's final
    Phase 2 decision string."""
    entry = stats.setdefault(concept, {"opportunities": 0, "profitable": 0})
    entry["opportunities"] += 1
    if decision in _PROFITABLE_DECISIONS:
        entry["profitable"] += 1
    return stats


def extract_concept_from_query(query: str, known_concepts: list[str]) -> str | None:
    """Best-effort: which configured concept (if any) appears in this query string."""
    q = query.lower()
    for concept in known_concepts:
        if concept.lower() in q:
            return concept
    return None
