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
items up for auction, to spot which represents the best value. Sometimes you'll only \
get ONE item (no direct peer to compare against) -- in that case, judge it against your \
general knowledge of typical NZ pricing for that kind of item instead.

You'll get a JSON array of items, each with: title, current auction price (NZD, may be \
null if bidding hasn't started), buy_now_price (NZD, may be null), condition, \
testing_level, and any comments/description from the listing.

Strongly prefer items in good condition, or needing only small/cosmetic fixes. Anything \
clearly damaged, faulty, or requiring major repair should already have been filtered out \
before reaching you -- if you spot such language anyway, score it low (1-3) regardless \
of price.

For EACH item, return:
- score (1-10): how good a value this specific item is. If comparing multiple items, \
  reward the best condition-for-price tradeoff, not just the lowest price. If judging \
  alone, reward how far below typical retail/resale value the price sits.
- reasons: up to 3 short phrases (under 8 words each) -- quick-scan bullet points.
- explanation: ONE concise sentence (max ~25 words) giving the single most important \
  reason for the score. Be specific to this item, not generic. No rambling, no hedging \
  filler -- get straight to the point a person actually needs.
- estimated_new_price_nzd: your best rough estimate of what this item costs brand new \
  in NZ right now, as an integer NZD. Ballpark from general knowledge, not a live quote -- \
  return null rather than guessing wildly if you genuinely don't know.
- suggested_resale_price_nzd: your best rough estimate of what THIS item, in its current \
  condition, would realistically sell for if relisted on Trade Me or Facebook Marketplace \
  NZ -- not brand-new retail, an honest secondhand price a buyer would actually pay given \
  the condition/testing notes. This is different from estimated_new_price_nzd (which is \
  retail) and should normally sit somewhere between the auction price and the new price, \
  adjusted for condition. Return null if you can't form a reasonable estimate.
- resale_likelihood: "high", "medium", or "low" -- how easily and quickly you'd expect this \
  specific item to resell if relisted on Trade Me or Facebook Marketplace NZ, based on how \
  common/in-demand that item type generally is in the NZ secondhand market. A rare or niche \
  item can still be a good "score" (great price for what it is) while having "low" resale \
  likelihood (small buyer pool, could sit unsold for a while) -- these are different \
  judgments, don't conflate them.
- resale_reason: one short phrase (under 10 words) explaining the resale_likelihood call.

Respond with ONLY a JSON array, no markdown fences, no preamble, one object per item in \
the SAME ORDER as given:
[{"score": <1-10>, "reasons": ["...", ...], "explanation": "...", "estimated_new_price_nzd": <int or null>, "suggested_resale_price_nzd": <int or null>, "resale_likelihood": "high"|"medium"|"low", "resale_reason": "..."}, ...]"""


def _extract_json(text: str) -> Optional[list]:
    text = text.strip()
    text = re.sub(r"^```(json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, list) else None
    except (json.JSONDecodeError, TypeError):
        return None


def score_group(items: List[Dict], api_key: str) -> List[Dict]:
    """Returns a list of {score, reasons, explanation, estimated_new_price_nzd}
    in the same order as `items`. On any failure, returns neutral fallback
    values for every item so the scanner never blocks or crashes on this step."""
    fallback = [{"score": None, "reasons": [], "explanation": "", "estimated_new_price_nzd": None, "suggested_resale_price_nzd": None, "resale_likelihood": None, "resale_reason": ""} for _ in items]

    if not api_key or not items:
        return fallback

    payload_items = [
        {
            "title": item.get("title", ""),
            "price_nzd": item.get("price"),
            "buy_now_price_nzd": item.get("buy_now_price"),
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
                "max_tokens": 1500,
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
        raw_text = "".join(text_blocks)
        parsed = _extract_json(raw_text)
        if not parsed or len(parsed) != len(items):
            print(f"[ai_value] response length mismatch or unparseable (expected {len(items)} items). Raw response: {raw_text[:500]}")
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

            resale_price = entry.get("suggested_resale_price_nzd")
            try:
                resale_price = int(resale_price) if resale_price is not None else None
            except (TypeError, ValueError):
                resale_price = None

            resale_likelihood = entry.get("resale_likelihood")
            if resale_likelihood not in ("high", "medium", "low"):
                resale_likelihood = None

            results.append({
                "score": score,
                "reasons": entry.get("reasons", [])[:3],
                "explanation": (entry.get("explanation") or "")[:250],
                "estimated_new_price_nzd": new_price,
                "suggested_resale_price_nzd": resale_price,
                "resale_likelihood": resale_likelihood,
                "resale_reason": (entry.get("resale_reason") or "")[:150],
            })
        return results
    except (requests.RequestException, ValueError) as e:
        print(f"[ai_value] request failed: {e}")
        return fallback
