"""Phase 2G support / spec section 18: liquidity estimation.

Heuristic and deliberately conservative -- returns "unknown"/wide time
ranges rather than false precision when evidence is thin.
"""
from __future__ import annotations

from scanner.models import ComparableEvidence


def estimate_liquidity(evidence: list[ComparableEvidence], current_listing_count: int = 0) -> tuple[str, str]:
    """Returns (liquidity_level, expected_sale_time_range)."""
    sold_count = sum(1 for e in evidence if e.is_sold)

    if sold_count >= 3:
        return "HIGH", "3-7 days"
    if sold_count >= 1 or current_listing_count >= 3:
        return "MEDIUM", "1-3 weeks"
    if evidence:
        return "LOW", "1-3 months"
    return "unknown", "unknown"
