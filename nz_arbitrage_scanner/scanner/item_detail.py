"""
Fetches condition, testing level, quantity, and description text from an
individual Turners item's detail page. Confirmed field names against a real
item page: "Condition", "Testing Level", "Quantity", "Comments".

Only called for items that are part of a similarity group (2+ items that
look like the same kind of thing) -- see scanner/grouping.py -- to keep
request volume reasonable rather than fetching every single search result.
"""
import re
from typing import Dict

import requests
from bs4 import BeautifulSoup

_LABELS = ["Condition", "Testing Level", "Quantity", "Comments"]


def fetch_item_detail(url: str, user_agent: str) -> Dict:
    result = {"condition": "", "testing_level": "", "quantity": "", "comments": ""}
    try:
        resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[item_detail] fetch failed for {url}: {e}")
        return result

    soup = BeautifulSoup(resp.text, "lxml")
    text = soup.get_text("\n", strip=True)

    # Extract each label's value as the text between it and the next known
    # label (or end of the "Item Details" block). This is regex-over-text
    # rather than tag-structure matching, since the exact HTML structure
    # wasn't verified live -- more resilient to minor markup differences.
    for i, label in enumerate(_LABELS):
        next_labels = _LABELS[i + 1:] + ["Contact & Location", "Contact & Auction Details"]
        boundary = "|".join(re.escape(l) for l in next_labels)
        pattern = rf"{re.escape(label)}\s*\n+\s*(.+?)(?:\n+(?:{boundary})|\Z)"
        m = re.search(pattern, text, re.DOTALL)
        if m:
            value = " ".join(m.group(1).split())[:500]
            key = label.lower().replace(" ", "_")
            result[key] = value

    return result
