"""Writes the scan results out as a dated CSV report, grouped by category."""
import csv
import os
from datetime import datetime
from typing import List, Dict

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")

FIELDNAMES = [
    "category",
    "source",
    "data_basis",
    "title",
    "url",
    "price_nzd",
    "buy_now_price_nzd",
    "condition",
    "location",
    "score",
    "reasons",
    "explanation",
    "estimated_new_price_nzd",
    "value_vs_new_pct",
    "suggested_resale_price_nzd",
    "potential_profit_nzd",
    "potential_profit_pct",
    "resale_likelihood",
    "resale_reason",
    "trademe_search_url",
    "facebook_search_url",
    "ebay_search_url",
    "notes",
]


def _sort_key(row: Dict):
    # Group by category (alphabetically, "Uncategorised" last), then within
    # a category put higher-scored items first (unscored last).
    category = row.get("category") or "Uncategorised"
    score = row.get("score")
    score_rank = (score is None, -(score or 0))
    return (category == "Uncategorised", category, score_rank, row.get("title", ""))


def write_report(rows: List[Dict]) -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    filename = f"opportunities_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    path = os.path.join(REPORTS_DIR, filename)

    sorted_rows = sorted(rows, key=_sort_key)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        current_category = None
        for row in sorted_rows:
            # Blank separator line between categories for readability when
            # opened in Excel/Sheets.
            if current_category is not None and row.get("category") != current_category:
                writer.writerow({k: "" for k in FIELDNAMES})
            current_category = row.get("category")
            writer.writerow({k: row.get(k, "") for k in FIELDNAMES})

    return path
