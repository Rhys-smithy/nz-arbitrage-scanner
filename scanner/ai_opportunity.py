"""
Reads each flagged auction's title + scraped blurb with Claude and asks it
to score how promising the auction looks as a resale opportunity (1-10),
with reasons why.

IMPORTANT CAVEAT: this is a judgment call based on the *text* available at
the auction-event level (branch, lot count, any promotional blurb) -- NOT
individual lot prices or condition, which aren't reliably scrapeable (see
README -- they load via JavaScript on a live bidding platform, which needs
much heavier tooling than this scanner uses). So the score reflects "how
promising does the listing LANGUAGE sound" (words like "unreserved,"
"liquidation," "deceased estate," "closing down") -- it is NOT comparing
real prices or condition against other auctions. Treat it as a triage
signal for where to spend your limited viewing time, not a valuation.

Uses Claude Haiku since this is a small, cheap, high-volume classification
task -- each call costs a fraction of a cent.
"""
import json
import re
from typing import Dict, Optional

import requests

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_VERSION = "2023-06-01"

SYSTEM_PROMPT = """You help a New Zealand auction reseller quickly triage which \
newly-listed auctions are worth their time to look into further. You'll be given \
an auction's title and whatever blurb/description text was scraped from its \
listing page (branch, lot count, promotional copy, etc -- NOT individual lot \
prices or condition, since those aren't available at this stage).

Score how promising the auction LANGUAGE suggests it might be as a resale \
opportunity, from 1 to 10:
- 8-10: strong signals (e.g. "unreserved," "liquidation," "deceased estate," "closing down," unusually high lot count)
- 4-7: some mildly positive signal, or just not enough information either way
- 1-3: language suggests caution (e.g. "sold as-is," "damaged stock") or nothing notable at all

This is NOT a price or value comparison -- you have no price or condition data, \
only listing language. Do not imply otherwise in your reasons.

Strongly prefer auctions that sound like they contain good-condition or lightly-used \
goods. If the blurb signals damaged, faulty, or "for parts" stock, score it low (1-3).

Respond with ONLY a JSON object, no markdown fences, no preamble:
{"score": <integer 1-10>, "reasons": ["short phrase", ...], "explanation": "one concise sentence", "flags": ["short phrase", ...], "resale_likelihood": "high"|"medium"|"low", "resale_reason": "short phrase"}

"reasons" = up to 3 short phrases explaining the score (why it might be worth a look).
"explanation" = ONE concise sentence (max ~25 words) -- the single most important reason for the score, given this is blurb-only, not real price data. No rambling.
"flags" = up to 3 short phrases noting any caution signals (e.g. "sold as-is," "damaged stock," "no viewing mentioned"). Empty list if none.
"resale_likelihood" = how easily/quickly this item TYPE would typically resell on Trade Me or Facebook Marketplace NZ if you had to guess from the title alone (common item = higher likelihood, niche/specialised = lower). This is independent of the score -- a great price on a niche item is still "low" resale likelihood.
"resale_reason" = one short phrase (under 10 words) for the resale_likelihood call.
Keep reason phrases under 8 words. If the text gives you nothing useful to go on, score it 4-5 (neutral) with empty reasons/flags rather than guessing high or low."""


def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    # Strip markdown fences if the model adds them despite instructions
    text = re.sub(r"^```(json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def analyze_listing(title: str, description: str, api_key: str) -> Dict:
    """Returns {score, reasons, flags}. `score` is None on any failure
    (missing key, API error, bad response) so the scanner never blocks on
    this step -- callers should treat None as "unrated", not zero."""
    fallback = {"score": None, "reasons": [], "explanation": "", "flags": [], "resale_likelihood": None, "resale_reason": ""}

    if not api_key:
        return fallback

    user_content = f"Title: {title}\n\nBlurb/description: {description[:1200]}"

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
                "max_tokens": 300,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_content}],
            },
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"[ai_opportunity] API error {resp.status_code}: {resp.text[:200]}")
            return fallback

        data = resp.json()
        text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
        parsed = _extract_json("".join(text_blocks))
        if not parsed or "score" not in parsed:
            return fallback

        try:
            score = int(parsed.get("score"))
            score = max(1, min(10, score))
        except (TypeError, ValueError):
            score = None

        resale_likelihood = parsed.get("resale_likelihood")
        if resale_likelihood not in ("high", "medium", "low"):
            resale_likelihood = None

        return {
            "score": score,
            "reasons": parsed.get("reasons", [])[:3],
            "explanation": (parsed.get("explanation") or "")[:250],
            "flags": parsed.get("flags", [])[:3],
            "resale_likelihood": resale_likelihood,
            "resale_reason": (parsed.get("resale_reason") or "")[:150],
        }
    except (requests.RequestException, ValueError) as e:
        print(f"[ai_opportunity] request failed: {e}")
        return fallback
