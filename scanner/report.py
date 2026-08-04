"""Writes the scan results out as a dated CSV report, grouped by category."""
import csv
import os
from datetime import datetime
from typing import List, Dict

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")

FIELDNAMES = [
    "category",
    "scanned_at",
    "source",
    "title",
    "url",
    "matched_keywords",
    "trademe_comparable_count",
    "trademe_median_price",
    "trademe_search_url",
    "facebook_search_url",
    "notes",
]


def _sort_key(row: Dict):
    # Group by category (alphabetically, "Uncategorised" last), then within
    # a category put the highest Trade Me comparable price first as a rough
    # "most worth a look" ordering.
    category = row.get("category") or "Uncategorised"
    price = row.get("trademe_median_price")
    price_sort = -(price if isinstance(price, (int, float)) and price else -1)
    return (category == "Uncategorised", category, price_sort)


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
