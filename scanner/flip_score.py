"""Phase 2G: deterministic Flip Score (0-100) and BUY/WATCH/PASS decision.

Replaces/extends the old 1-10 generic AI score with a fully deterministic,
explainable, configurably-weighted score. AI never sets this number
directly -- it only supplies the upstream inputs (valuation, confidence,
liquidity, condition risk) that feed the formula below.
"""
from __future__ import annotations

from scanner.bankroll import capital_concentration_pct, exceeds_concentration_limit
from scanner.models import Opportunity

_LIQUIDITY_FACTOR = {"HIGH": 1.0, "MEDIUM": 0.6, "LOW": 0.3, "unknown": 0.0}
_CONDITION_RISK_FACTOR = {"low": 1.0, "medium": 0.5, "high": 0.0, "unknown": 0.3}

_BANDS = [
    (85, "EXCELLENT"),
    (70, "STRONG"),
    (55, "WATCH"),
    (45, "WEAK"),
]


def _band(score: int) -> str:
    for threshold, label in _BANDS:
        if score >= threshold:
            return label
    return "PASS"


def compute_flip_score(opportunity: Opportunity, weights: dict, bankroll_cfg: dict) -> int:
    w = weights
    total = 0.0

    # 1. Expected net profit vs. minimum_profit target (full points at 3x target)
    min_profit = max(1.0, bankroll_cfg.get("minimum_profit", 10))
    profit = opportunity.expected_net_profit_low
    profit_factor = 0.0 if profit is None else max(0.0, min(1.0, profit / (min_profit * 3)))
    total += w.get("expected_net_profit", 25) * profit_factor

    # 2. ROI vs. minimum_roi_percent target (full points at 3x target)
    min_roi = max(1.0, bankroll_cfg.get("minimum_roi_percent", 40))
    roi = opportunity.roi_low_pct
    roi_factor = 0.0 if roi is None else max(0.0, min(1.0, roi / (min_roi * 3)))
    total += w.get("roi", 20) * roi_factor

    # 3. Valuation confidence
    conf_factor = (opportunity.valuation.confidence_pct or 0.0) / 100.0
    total += w.get("valuation_confidence", 20) * conf_factor

    # 4. Liquidity
    total += w.get("liquidity", 15) * _LIQUIDITY_FACTOR.get(opportunity.liquidity, 0.0)

    # 5. Price confidence (evidence quantity/quality proxy: # comparables, capped at 4)
    evidence_factor = min(1.0, len(opportunity.valuation.evidence) / 4.0)
    total += w.get("price_confidence", 10) * evidence_factor

    # 6. Condition risk (inverse)
    risk_level = opportunity.identification.condition_risk_level
    total += w.get("condition_risk", 5) * _CONDITION_RISK_FACTOR.get(risk_level, 0.3)

    # 7. Capital concentration (inverse)
    if opportunity.current_price is not None:
        available_cash = bankroll_cfg.get("starting_bankroll", 500)
        conc = capital_concentration_pct(opportunity.current_price, available_cash)
        opportunity.capital_concentration_pct = conc
        conc_factor = max(0.0, 1.0 - conc / 100.0)
        total += w.get("capital_concentration", 5) * conc_factor

    max_possible = sum(w.values()) or 100
    score = round(total / max_possible * 100)
    return max(0, min(100, score))


def decide(opportunity: Opportunity, bankroll_cfg: dict) -> tuple[str, list[str]]:
    """Return (decision, reasons). Decision in BUY/WATCH/PASS/PROFITABLE BUT CAPITAL RISK."""
    reasons: list[str] = []

    if opportunity.current_price is None or opportunity.valuation.quick_sale_low is None:
        return "PASS", ["Missing price or valuation data"]

    min_profit = bankroll_cfg.get("minimum_profit", 0)
    min_roi = bankroll_cfg.get("minimum_roi_percent", 0)

    profit_ok = (opportunity.expected_net_profit_low or 0) >= min_profit
    roi_ok = (opportunity.roi_low_pct or 0) >= min_roi

    if not profit_ok:
        reasons.append(f"Expected profit below minimum target (${min_profit})")
    if not roi_ok:
        reasons.append(f"ROI below minimum target ({min_roi}%)")

    if not profit_ok or not roi_ok:
        return "PASS", reasons

    if opportunity.valuation.confidence_pct < 40:
        reasons.append("Valuation confidence too low")
        return "WATCH", reasons

    concentration_breach = exceeds_concentration_limit(
        opportunity.current_price, bankroll_cfg.get("starting_bankroll", 500), bankroll_cfg
    )

    band = opportunity.flip_score_band
    within_budget = (
        opportunity.max_buy_price is not None
        and opportunity.current_price <= opportunity.max_buy_price
    )

    if concentration_breach:
        reasons.append(
            f"Purchase would use >{bankroll_cfg.get('maximum_single_purchase_percent')}% of available bankroll"
        )
        if profit_ok and roi_ok:
            return "PROFITABLE BUT CAPITAL RISK", reasons

    if band in ("EXCELLENT", "STRONG") and within_budget:
        reasons.append(f"Flip score {opportunity.flip_score}/100 ({band})")
        return "BUY", reasons

    if band == "WATCH" or not within_budget:
        if not within_budget:
            reasons.append("Current price exceeds maximum buy price")
        return "WATCH", reasons

    reasons.append(f"Flip score {opportunity.flip_score}/100 too low")
    return "PASS", reasons


def score_and_decide(opportunity: Opportunity, weights: dict, bankroll_cfg: dict) -> Opportunity:
    opportunity.flip_score = compute_flip_score(opportunity, weights, bankroll_cfg)
    opportunity.flip_score_band = _band(opportunity.flip_score)
    opportunity.decision, opportunity.decision_reasons = decide(opportunity, bankroll_cfg)
    return opportunity
