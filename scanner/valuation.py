"""Phase 2E/2F: deterministic cost, profit, ROI and maximum-buy-price engine.

Everything here is plain Python arithmetic. AI never computes final
numbers -- it only ever supplies *inputs* (resale estimates, confidence)
that this module turns into money. This mirrors the pattern the existing
codebase already uses in main.py._build_row()/xlsx_report.py, just made
explicit, reusable, and testable.
"""
from __future__ import annotations

from scanner.models import CostBreakdown, Opportunity, ResaleValuation


def build_costs(purchase_price: float, cost_model: dict) -> CostBreakdown:
    """Build a CostBreakdown from config["cost_model"] percentages/flats."""
    purchase_price = max(0.0, float(purchase_price or 0.0))
    pct = lambda key: purchase_price * (float(cost_model.get(key, 0.0)) / 100.0)
    return CostBreakdown(
        purchase_price=purchase_price,
        buyer_premium=round(pct("buyer_premium_percent"), 2),
        gst=round(pct("gst_percent"), 2),
        selling_fees=round(pct("selling_fee_percent"), 2),
        payment_fees=round(pct("payment_fee_percent"), 2),
        shipping=round(float(cost_model.get("shipping_flat", 0.0)), 2),
        packaging=round(float(cost_model.get("packaging_flat", 0.0)), 2),
        repair_allowance=round(pct("repair_allowance_percent"), 2),
        negotiation_allowance=round(pct("negotiation_allowance_percent"), 2),
    )


def compute_profit_and_roi(opportunity: Opportunity) -> None:
    """Fill expected_net_profit_low/high and roi_low/high on `opportunity` in place.

    Uses the QUICK SALE value only, per spec section 10: "The financial
    recommendation must primarily use the Quick Sale value."

    Phase 4B follow-up (Run #35 live validation finding): "expected profit"
    and "ROI" are forecast language -- they imply current_price is a real
    cost basis. When price_type == "starting_bid", current_price is the
    auction's opening number with zero bids placed; it has no evidentiary
    relationship to what the item will actually sell for; computing a
    profit/ROI "forecast" off it would be exactly the misleading
    acquisition-price representation the audit flagged (a $1 opening bid
    on a real item mechanically produces a 1000%+ ROI number that means
    nothing). So: for starting-bid candidates specifically, profit/ROI are
    left unset (None) rather than computed off an unrealistic basis --
    NOT replaced with an invented/estimated "more realistic" price.
    current_price itself is untouched here and still flows everywhere else
    (display, cost modelling, bidding_room) as the real observed bid.
    Every other price_type (current_bid, buy_now, or non-Turners sources
    where price_type is None) is completely unaffected by this check.
    """
    val = opportunity.valuation
    costs = opportunity.costs
    if opportunity.current_price is None:
        return
    if opportunity.price_type == "starting_bid":
        return

    total_cost = costs.total  # purchase price + all fees/costs
    if val.quick_sale_low is not None:
        opportunity.expected_net_profit_low = round(val.quick_sale_low - total_cost, 2)
    if val.quick_sale_high is not None:
        opportunity.expected_net_profit_high = round(val.quick_sale_high - total_cost, 2)

    if total_cost > 0:
        if opportunity.expected_net_profit_low is not None:
            opportunity.roi_low_pct = round((opportunity.expected_net_profit_low / total_cost) * 100, 1)
        if opportunity.expected_net_profit_high is not None:
            opportunity.roi_high_pct = round((opportunity.expected_net_profit_high / total_cost) * 100, 1)


def compute_max_buy_price(
    quick_sale_value: float,
    costs_excluding_purchase: float,
    minimum_profit: float,
    minimum_roi_percent: float = 0.0,
) -> float:
    """Highest purchase price that still clears BOTH the minimum profit target
    AND the minimum ROI target, given a fixed quick-sale resale value.

    max_buy s.t.
      quick_sale - costs_excl - max_buy            >= minimum_profit
      (quick_sale - costs_excl - max_buy) / (max_buy + costs_excl) >= minimum_roi_percent / 100

    Returns 0.0 (never negative) if no purchase price clears the targets.
    """
    if quick_sale_value is None:
        return 0.0
    quick_sale_value = float(quick_sale_value)
    costs_excluding_purchase = float(costs_excluding_purchase or 0.0)

    # Profit-target cap
    cap_from_profit = quick_sale_value - costs_excluding_purchase - minimum_profit

    # ROI-target cap: profit / (buy + costs_excl) >= roi -> buy <= (profit)/(1+roi) - costs_excl
    # where profit = quick_sale - costs_excl - buy substituted through:
    #   quick_sale - costs_excl - buy >= r * (buy + costs_excl)   [r = roi/100]
    #   quick_sale - costs_excl - r*costs_excl >= buy*(1+r)
    #   buy <= (quick_sale - costs_excl*(1+r)) / (1+r)
    r = minimum_roi_percent / 100.0
    if (1 + r) > 0:
        cap_from_roi = (quick_sale_value - costs_excluding_purchase * (1 + r)) / (1 + r)
    else:
        cap_from_roi = cap_from_profit

    max_buy = min(cap_from_profit, cap_from_roi)
    return round(max(0.0, max_buy), 2)


def compute_bidding_room(current_price: float, max_buy_price: float) -> float:
    if current_price is None or max_buy_price is None:
        return 0.0
    return round(max(0.0, max_buy_price - current_price), 2)


def apply_valuation(opportunity: Opportunity, cost_model: dict, bankroll_cfg: dict) -> Opportunity:
    """One-shot pipeline: build costs -> profit/ROI -> max buy price -> bidding room.

    Mutates and returns `opportunity`. Deterministic and side-effect-free
    beyond the object passed in, so it's directly unit-testable with
    hand-built Opportunity/ResaleValuation fixtures (no network, no AI).
    """
    opportunity.costs = build_costs(opportunity.current_price or 0.0, cost_model)
    compute_profit_and_roi(opportunity)

    val = opportunity.valuation
    if val.quick_sale_low is not None:
        costs_excl_purchase = opportunity.costs.total_excluding_purchase
        opportunity.max_buy_price = compute_max_buy_price(
            quick_sale_value=val.quick_sale_low,
            costs_excluding_purchase=costs_excl_purchase,
            minimum_profit=bankroll_cfg.get("minimum_profit", 0),
            minimum_roi_percent=bankroll_cfg.get("minimum_roi_percent", 0),
        )
        if opportunity.current_price is not None:
            opportunity.bidding_room = compute_bidding_room(
                opportunity.current_price, opportunity.max_buy_price
            )

    return opportunity
