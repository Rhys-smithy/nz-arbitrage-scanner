"""Phase 4B.2: persistence for the authoritative discovery-pipeline
Opportunity results.

Serializes scanner.models.Opportunity objects produced by
scanner/discover.py::run_discovery() to a dated JSON report under
reports/, plus a small index manifest for locating the latest/historical
runs. This is a pure passthrough of the Opportunity dataclass -- it does
not compute, reinterpret, or invent any valuation/scoring/decision data.
The only additions beyond dataclasses.asdict() are the three @property
values (CostBreakdown.total/.total_excluding_purchase,
ResaleValuation.quick_sale_mid) that asdict() can't see, since those
aren't dataclass fields -- resolved here so a UI reading this file never
needs its own copy of that arithmetic.

Deliberately separate from scanner/report.py and scanner/xlsx_report.py,
which serve the older row-dict scan pipeline (different schema -- see
CLAUDE.md/PROJECT_STATE.md). This module must not be imported by, or
merged into, that pipeline.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone

from scanner.models import Opportunity

SCHEMA_VERSION = 1

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")
DEFAULT_INDEX_PATH = os.path.join(REPORTS_DIR, "discovery_index.json")


def _opportunity_to_dict(o: Opportunity) -> dict:
    """asdict() recurses through every nested dataclass field
    (identification, valuation, costs, valuation.evidence) automatically --
    but it only sees dataclass *fields*, not @property values, so
    CostBreakdown.total/.total_excluding_purchase and
    ResaleValuation.quick_sale_mid are absent from a bare asdict() result.
    Inject them explicitly so the JSON is self-contained."""
    d = asdict(o)
    d["costs"]["total"] = o.costs.total
    d["costs"]["total_excluding_purchase"] = o.costs.total_excluding_purchase
    d["valuation"]["quick_sale_mid"] = o.valuation.quick_sale_mid
    return d


def write_discovery_report(
    opportunities: list[Opportunity], run_meta: dict, reports_dir: str = REPORTS_DIR
) -> tuple[str, dict]:
    """Writes reports/discovery_<timestamp>.json containing every
    Opportunity from this run -- BUY, WATCH, PASS, and PROFITABLE BUT
    CAPITAL RISK alike (unlike today's Telegram alerts, which are
    BUY-only) -- plus the run_meta envelope the caller supplies.

    `run_meta` must contain only values the caller already computed during
    the run (query/candidate/verification counts, decision tally, etc) --
    this function does not calculate or invent any metric itself, and does
    not touch valuation/scoring/decision logic.

    Returns (path, full_payload_dict) so callers/tests can inspect exactly
    what was written without re-reading the file.
    """
    payload = {
        "schema_version": SCHEMA_VERSION,
        **run_meta,
        "opportunities": [_opportunity_to_dict(o) for o in opportunities],
    }

    os.makedirs(reports_dir, exist_ok=True)
    filename = f"discovery_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    path = os.path.join(reports_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    return path, payload


def _load_index(index_path: str) -> dict:
    if not os.path.exists(index_path):
        return {"generated_at": None, "count": 0, "reports": []}
    try:
        with open(index_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"generated_at": None, "count": 0, "reports": []}


def update_discovery_index(
    path: str, payload: dict, index_path: str = DEFAULT_INDEX_PATH
) -> dict:
    """Appends an entry for this run to reports/discovery_index.json
    (newest first), so a UI/human can find the latest run
    (index["reports"][0]) or browse history without listing the reports/
    directory directly. Mirrors the existing reports/index.json manifest
    pattern (built for the legacy CSV pipeline in
    .github/workflows/scan.yml) but kept as a separate file, since that
    manifest's schema (csv/xlsx/rows) is specific to the scan pipeline.

    Reads only the fields write_discovery_report() already put in
    `payload` -- no new computation.
    """
    index = _load_index(index_path)
    entry = {
        "json": os.path.basename(path),
        "run_timestamp": payload.get("run_timestamp"),
        "opportunity_count": payload.get("opportunity_count"),
        "decision_counts": payload.get("decision_counts"),
    }
    index["reports"].insert(0, entry)
    index["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    index["count"] = len(index["reports"])

    os.makedirs(os.path.dirname(index_path) or ".", exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)

    return index
