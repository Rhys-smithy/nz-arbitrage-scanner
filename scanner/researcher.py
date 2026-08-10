"""Phase 3 section 11: Researcher pass.

Interprets already-gathered evidence into a plain-English summary,
uncertainty note, and likely resale channels. Deliberately does NOT
compute the resale numbers itself -- scanner/comparables.py's
build_valuation_from_evidence() (Python, deterministic) remains the
source of truth for quick/normal/optimistic values. The Researcher's
output is descriptive context for a human (and for the Trader pass),
not a replacement for that arithmetic.

Same safe-fallback pattern as scanner/ai_value.py: no API key or any
failure -> neutral output, never raises, never fabricates.
"""
from __future__ import annotations

import json
import re

import requests

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_VERSION = "2023-06-01"

_PROMPT = """You are a resale-market researcher. You are given a listing and a list of \
comparable evidence already gathered from search results (NOT to be second-guessed on price -- \
that arithmetic is handled separately). Summarise what the evidence shows.

Listing: {title}
Current asking price: {price}

Comparable evidence (JSON):
{evidence_json}

Respond with ONLY a JSON object:
{{
  "evidence_summary": "1-2 sentence plain-English summary of what the evidence shows",
  "uncertainty": "low" | "medium" | "high",
  "likely_resale_channels": ["Trade Me", "eBay", ...],
  "concerns": ["short phrase", ...]
}}

Do not state a specific resale price yourself -- that is calculated separately from the evidence.
If evidence is sparse or weak, say so plainly in evidence_summary and set uncertainty accordingly.
"""


def research(title: str, price, evidence: list, api_key: str) -> dict:
    fallback = {
        "evidence_summary": "AI research unavailable (no API key or request failed).",
        "uncertainty": "high",
        "likely_resale_channels": [],
        "concerns": [],
    }
    if not api_key:
        return fallback

    evidence_json = json.dumps(
        [
            {
                "price": e.price, "source": e.source, "evidence_type": e.evidence_type,
                "similarity_score": e.similarity_score, "date_observed": e.date_observed,
            }
            for e in evidence
        ]
    )

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
                "max_tokens": 400,
                "messages": [{
                    "role": "user",
                    "content": _PROMPT.format(title=title or "", price=price, evidence_json=evidence_json),
                }],
            },
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.json()["content"][0]["text"]
        match = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(match.group(0)) if match else {}
        return {**fallback, **data}
    except Exception:
        return fallback
