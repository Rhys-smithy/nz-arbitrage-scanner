"""Tiny JSON-file cache of URLs we've already flagged, so repeat runs only
surface NEW listings instead of re-reporting the same auction every time."""
import json
import os
from typing import Set

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "seen.json")


def load_seen(path: str = DEFAULT_PATH) -> Set[str]:
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError):
        return set()


def save_seen(seen: Set[str], path: str = DEFAULT_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, indent=2)
