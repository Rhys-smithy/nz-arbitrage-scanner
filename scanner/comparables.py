"""Phase 2D: comparable-evidence aggregation and confidence scoring.

Deterministic. Given a list of ComparableEvidence (already gathered by
search sources / AI extraction), this computes the three resale values
and a confidence percentage. It does NOT invent evidence -- if the list
is empty, it returns an explicit "Insufficient comparable evidence" note
and 0% confidence rather than guessing (spec section 24 & 34).
"""
from __future__ import annotations

from datetime import datetime, timezone

from scanner.models import ComparableEvidence, ResaleValuation

_SOURCE_WEIGHT = {
    # Higher = more trustworthy for second-hand resale valuation.
    # Retail prices are intentionally weighted lowest per spec section 9.
    "sold_nz": 1.0,
    "observed_nz": 0.85,
    "current_listing_nz": 0.6,
    "sold_international": 0.5,
    "retail": 0.15,
}

# Phase 4B.5 (Run #37/#38 instability fix): minimum title-similarity a
# comparable must have to be trusted for PRICE calculations (quick_sale_low/
# high/normal/optimistic) and confidence. Validated against the real
# evidence behind Run #37/#38's Yamaha AG125, Fuji C325 Copier, and Yamaha
# YZF-R3A instability (see PROJECT_STATE.md / branch history) -- 0.30 was
# the lowest threshold that stopped a single near-zero-similarity result
# (e.g. an unrelated $1 auction page, a mis-matched motorbike-parts listing)
# from setting quick_sale_low/optimistic outright, without discarding
# borderline-but-genuine comparables that 0.35 started dropping.
# Deliberately separate from config.json's `similarity_threshold`, which is
# scanner/grouping.py's unrelated legacy same-category Turners clustering
# threshold -- do not conflate the two.
MIN_COMPARABLE_SIMILARITY = 0.30


def _recency_factor(date_observed: str) -> float:
    try:
        dt = datetime.fromisoformat(date_observed)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc) - dt).days
    except Exception:
        return 0.5
    if days <= 14:
        return 1.0
    if days <= 60:
        return 0.75
    if days <= 180:
        return 0.5
    return 0.25


def compute_confidence(evidence: list[ComparableEvidence], model_identified_confidently: bool) -> float:
    if not evidence:
        return 0.0

    weighted = []
    for e in evidence:
        base = 1.0 if e.is_sold else 0.7
        similarity = max(0.0, min(1.0, e.similarity_score))
        recency = _recency_factor(e.date_observed)
        weighted.append(base * similarity * recency)

    coverage = min(1.0, len(evidence) / 4.0)  # more comparables = more confidence, caps at 4
    consistency = _price_consistency_factor(evidence)
    model_factor = 1.0 if model_identified_confidently else 0.6

    raw = (sum(weighted) / len(weighted)) * coverage * consistency * model_factor
    return round(max(0.0, min(1.0, raw)) * 100, 1)


def _price_consistency_factor(evidence: list[ComparableEvidence]) -> float:
    prices = [e.price for e in evidence if e.price]
    if len(prices) < 2:
        return 0.8  # can't measure spread with <2 points; mild penalty
    lo, hi = min(prices), max(prices)
    if hi == 0:
        return 0.5
    spread = (hi - lo) / hi
    # Tight spread -> high consistency; wide spread -> penalise confidence.
    return max(0.3, 1.0 - spread)


def build_valuation_from_evidence(
    evidence: list[ComparableEvidence], model_identified_confidently: bool
) -> ResaleValuation:
    # Full, unfiltered evidence is always preserved on the returned
    # valuation for reporting/UI -- never hidden, even when excluded from
    # the price/confidence calculations below (see MIN_COMPARABLE_SIMILARITY).
    val = ResaleValuation(evidence=list(evidence))

    if not evidence:
        val.evidence_note = "Insufficient comparable evidence."
        val.confidence_pct = 0.0
        return val

    # Phase 4B.5: only evidence similar enough to the listing to trust for
    # pricing may set quick_sale_low/high/normal/optimistic or feed
    # confidence -- a near-zero-similarity comparable (wrong model, unrelated
    # item, stray page) must never be able to set the price floor/ceiling
    # just because it happened to have an extractable price. It is still
    # visible in val.evidence above for a human to inspect.
    qualified = [
        e for e in evidence if e.price and e.similarity_score >= MIN_COMPARABLE_SIMILARITY
    ]

    if not qualified:
        val.evidence_note = (
            "Insufficient comparable evidence: no comparable met the minimum "
            f"similarity threshold ({MIN_COMPARABLE_SIMILARITY:.0%})."
        )
        val.confidence_pct = 0.0
        return val

    prices = sorted(e.price for e in qualified)
    n = len(prices)
    low_idx = 0
    mid_idx = n // 2
    median = prices[mid_idx] if n % 2 else (prices[mid_idx - 1] + prices[mid_idx]) / 2

    val.quick_sale_low = round(prices[low_idx] * 0.9, 2)
    val.quick_sale_high = round(median * 0.95, 2)
    val.normal = round(median, 2)
    val.optimistic = round(prices[-1], 2)
    val.confidence_pct = compute_confidence(qualified, model_identified_confidently)

    if val.confidence_pct < 40:
        val.evidence_note = "Low confidence: few or weak comparables -- treat estimate as rough."

    return val
