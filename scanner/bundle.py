"""Phase 2C (deterministic half) + spec section 8: bundle arbitrage math.

Component *estimates* come from AI product identification
(scanner/product_id.py); turning those estimates into the four required
bundle values is pure, deterministic Python -- no AI arithmetic.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BundleValuation:
    gross_component_value: float
    quick_sale_bundle_value: float
    normal_resale_value: float
    component_breakup_value: float
    maximum_realistic_value: float


def value_bundle(
    component_quick_values: list[float],
    breakup_discount_pct: float = 25.0,
    selling_cost_pct: float = 12.0,
) -> BundleValuation:
    """
    component_quick_values: quick-sale estimate for each identified component.
    breakup_discount_pct: realistic haircut applied when selling components
        separately vs. naive sum (time cost, imperfect buyers per part, risk
        of unsold leftovers) -- NOT optimistic retail stacking.
    selling_cost_pct: fees/shipping/time cost eaten when selling as a whole
        bundle in one listing (usually cheaper per-item than piecemeal).
    """
    gross = round(sum(v for v in component_quick_values if v is not None), 2)

    # Whole-bundle quick sale: gross value minus selling costs minus an
    # additional "bundle discount" a buyer expects for taking everything at once.
    quick_sale_bundle = round(gross * (1 - selling_cost_pct / 100) * 0.85, 2)

    # Normal resale (a bit more patience, same channel): less aggressive discount
    normal_resale = round(gross * (1 - selling_cost_pct / 100) * 0.95, 2)

    # Component breakup: sum of per-part quick-sale values minus the
    # breakup discount (extra listings, extra buyers, partial unsold risk)
    component_breakup = round(gross * (1 - breakup_discount_pct / 100), 2)

    maximum_realistic = round(max(quick_sale_bundle, normal_resale, component_breakup), 2)

    return BundleValuation(
        gross_component_value=gross,
        quick_sale_bundle_value=quick_sale_bundle,
        normal_resale_value=normal_resale,
        component_breakup_value=component_breakup,
        maximum_realistic_value=maximum_realistic,
    )
