"""Phase 3 section 11: Trader pass.

Challenges the Researcher's read of the evidence and, where warranted,
tells the deterministic engine to REDO the valuation with weaker evidence
excluded. The Trader never invents a number itself -- it can only flag
which existing evidence entries look unreliable; Python
(scanner.comparables.build_valuation_from_evidence) then recomputes with
those excluded. This keeps arithmetic entirely in Python (spec section 20)
while giving the "challenge the researcher" behaviour real teeth.
"""
from __future__ import annotations

import json
import re

import requests

from scanner.comparables import build_valuation_from_evidence
from scanner.models import ResaleValuation

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_VERSION = "2023-06-01"

_PROMPT = """You are a skeptical trader deciding whether to risk real money on a resale flip. \
You are given the listing, the researcher's read of the evidence, the raw comparable evidence, \
current costs, and the buyer's available bankroll. Your job is to find reasons this deal is \
weaker than it looks -- not to talk yourself into it.

Listing: {title}
Current price: {price}
Available bankroll: {bankroll}
Total cost excluding purchase: {costs_excl}

Researcher summary: {researcher_summary}
Researcher uncertainty: {uncertainty}

Comparable evidence (JSON, each has an index you can reference):
{evidence_json}

Look specifically for: weak/loose comparables (low similarity_score), optimistic asking prices \
being treated as achievable, wrong model matches, condition differences, low liquidity signals, \
high shipping/international costs, excessive capital concentration, hidden repair risk.

Respond with ONLY a JSON object:
{{
  "reject_valuation": boolean,
  "weak_evidence_indices": [int, ...],
  "reasoning": "1-3 sentences",
  "liquidity_concern": boolean
}}

weak_evidence_indices lists the 0-based indices of evidence entries you think should be EXCLUDED \
from the valuation (wrong model, too dissimilar, unreliable). Only flag evidence you have a \
specific reason to distrust -- don't flag everything reflexively.
"""


def trader_review(
    title: str,
    price,
    researcher_result: dict,
    evidence: list,
    costs_excl_purchase: float,
    bankroll: float,
    api_key: str,
) -> tuple[ResaleValuation, dict]:
    """Returns (possibly-adjusted ResaleValuation, trader_verdict dict).

    If no API key / call fails: returns the original evidence-based
    valuation unchanged, with a verdict noting the trader pass didn't run
    (never silently pretends a review happened).
    """
    fallback_valuation = build_valuation_from_evidence(
        evidence, model_identified_confidently=True
    )
    fallback_verdict = {
        "reject_valuation": False,
        "weak_evidence_indices": [],
        "reasoning": "Trader review unavailable (no API key or request failed) -- using unreviewed evidence-based valuation.",
        "liquidity_concern": False,
        "ran": False,
    }

    if not api_key or not evidence:
        return fallback_valuation, fallback_verdict

    evidence_json = json.dumps(
        [
            {"index": i, "price": e.price, "source": e.source, "evidence_type": e.evidence_type,
             "similarity_score": e.similarity_score}
            for i, e in enumerate(evidence)
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
                    "content": _PROMPT.format(
                        title=title or "", price=price, bankroll=bankroll,
                        costs_excl=costs_excl_purchase,
                        researcher_summary=researcher_result.get("evidence_summary", ""),
                        uncertainty=researcher_result.get("uncertainty", "unknown"),
                        evidence_json=evidence_json,
                    ),
                }],
            },
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.json()["content"][0]["text"]
        match = re.search(r"\{.*\}", text, re.DOTALL)
        verdict = json.loads(match.group(0)) if match else {}
    except Exception:
        return fallback_valuation, fallback_verdict

    verdict = {**fallback_verdict, **verdict, "ran": True}
    weak_indices = set(verdict.get("weak_evidence_indices") or [])
    kept_evidence = [e for i, e in enumerate(evidence) if i not in weak_indices]

    # Deterministic Python recompute with the trader-flagged weak evidence
    # excluded -- the trader never sets the number itself.
    adjusted_valuation = build_valuation_from_evidence(
        kept_evidence, model_identified_confidently=not verdict.get("reject_valuation", False)
    )
    if verdict.get("reject_valuation") and not kept_evidence:
        adjusted_valuation.evidence_note = (
            "Trader rejected valuation and no reliable evidence remained: "
            + verdict.get("reasoning", "")
        )

    return adjusted_valuation, verdict
