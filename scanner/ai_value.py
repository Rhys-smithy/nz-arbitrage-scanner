"""
Given a group of similar items (same rough type, e.g. multiple "18V Drill"
listings) with REAL price and condition data scraped from Turners, asks
Claude to score each item's relative value 1-10 and explain why -- this is
the genuine price+condition comparison, unlike ai_opportunity.py which only
has blurb text to go on for Thorntons/Mainland Auctions.

Also asks for a rough estimate of typical NEW/retail price for the item,
so you can see roughly how far below retail the auction price sits. This
estimate comes from Claude's general knowledge, NOT a live price lookup --
it can be wrong, especially for newer products released after training data
cutoff, regional pricing differences, or less common items. Treat it as a
ballpark sanity-check, not a quote. Always verify anything that matters
with an actual current retail listing before relying on it.
"""
import json
import re
from typing import Dict, List, Optional

import requests

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_VERSION = "2023-06-01"

SYSTEM_PROMPT = """You help a New Zealand auction reseller compare several similar \
items up for auction, to spot which represents the best value.

You'll get a JSON array of items of the same rough type (e.g. several "18V Drill" \
listings), each with: title, current auction price (NZD), condition, testing_level, \
and any comments/description from the listing.

For EACH item, return:
- score (1-10): how good a value this specific item is, considering BOTH its price \
  relative to the other items in the group AND its condition. A cheaper item in worse \
  condition and a pricier item in better condition might score similarly -- reward the \
  item with the best condition-for-price tradeoff, not just the lowest price.
- reasons: up to 3 short phrases (under 8 words each) explaining the score
- estimated_new_price_nzd: your best rough estimate of what this item costs brand new \
  in NZ right now, as an integer NZD. This is a ballpark from general knowledge, not a \
  live quote -- if you genuinely don't know (obscure item, could be very outdated \
  knowledge, wildly variable pricing), return null rather than guessing wildly.

Respond with ONLY a JSON array, no markdown fences, no preamble, one object per item in \
the SAME ORDER as given:
[{"score": <1-10>, "reasons": ["...", ...], "estimated_new_price_nzd": <int or null>}, ...]"""


def _extract_json(text: str) -> Optional[list]:
    text = text.strip()
    text = re.sub(r"^```(json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, list) else None
    except (json.JSONDecodeError, TypeError):
        return None


def score_group(items: List[Dict], api_key: str) -> List[Dict]:
    """Returns a list of {score, reasons, estimated_new_price_nzd} in the
    same order as `items`. On any failure, returns neutral fallback values
    for every item so the scanner never blocks or crashes on this step."""
    fallback = [{"score": None, "reasons": [], "estimated_new_price_nzd": None} for _ in items]

    if not api_key or not items:
        return fallback

    payload_items = [
        {
            "title": item.get("title", ""),
            "price_nzd": item.get("price"),
            "condition": item.get("condition", "not specified"),
            "testing_level": item.get("testing_level", "not specified"),
            "comments": (item.get("comments", "") or "")[:300],
        }
        for item in items
    ]

    try:
        resp = requests.post(
            API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 800,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": json.dumps(payload_items)}],
            },
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"[ai_value] API error {resp.status_code}: {resp.text[:200]}")
            return fallback

        data = resp.json()
        text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
        parsed = _extract_json("".join(text_blocks))
        if not parsed or len(parsed) != len(items):
            print(f"[ai_value] response length mismatch or unparseable, got: {parsed}")
            return fallback

        results = []
        for entry in parsed:
            try:
                score = int(entry.get("score"))
                score = max(1, min(10, score))
            except (TypeError, ValueError):
                score = None
            new_price = entry.get("estimated_new_price_nzd")
            try:
                new_price = int(new_price) if new_price is not None else None
            except (TypeError, ValueError):
                new_price = None
            results.append({
                "score": score,
                "reasons": entry.get("reasons", [])[:3],
                "estimated_new_price_nzd": new_price,
            })
        return results
    except (requests.RequestException, ValueError) as e:
        print(f"[ai_value] request failed: {e}")
        return fallback
