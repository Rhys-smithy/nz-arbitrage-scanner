import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest

from scanner.flip_score import compute_flip_score, decide, score_and_decide
from scanner.models import ComparableEvidence, Opportunity, ProductIdentification, ResaleValuation

WEIGHTS = {
    "expected_net_profit": 25, "roi": 20, "valuation_confidence": 20,
    "liquidity": 15, "price_confidence": 10, "condition_risk": 5, "capital_concentration": 5,
}
BANKROLL_CFG = {
    "starting_bankroll": 500, "target_bankroll": 10000, "minimum_profit": 10,
    "minimum_roi_percent": 40, "maximum_single_purchase_percent": 40,
}


def _strong_opportunity():
    o = Opportunity(title="Nikon D90 bundle", url="u", source="Turners", current_price=165)
    o.valuation = ResaleValuation(
        quick_sale_low=280, quick_sale_high=310, confidence_pct=87,
        evidence=[
            ComparableEvidence("Nikon D90", "D90", "used", 310, "NZD", "TradeMe", "u1", "2026-08-01", 0.95, True),
            ComparableEvidence("Nikon D90", "D90", "used", 325, "NZD", "TradeMe", "u2", "2026-08-01", 0.9, True),
        ],
    )
    o.identification = ProductIdentification(brand="Nikon", model="D90", model_identified_confidently=True,
                                              condition_risk_level="low")
    o.liquidity = "HIGH"
    o.expected_net_profit_low = 90
    o.roi_low_pct = 55
    o.max_buy_price = 210
    return o


class TestFlipScore(unittest.TestCase):
    def test_strong_opportunity_scores_high(self):
        o = _strong_opportunity()
        score = compute_flip_score(o, WEIGHTS, BANKROLL_CFG)
        self.assertGreaterEqual(score, 55)
        self.assertLessEqual(score, 100)

    def test_weak_opportunity_scores_low(self):
        o = Opportunity(title="mystery box", url="u", source="Thorntons", current_price=100)
        o.valuation = ResaleValuation()  # no evidence, no confidence
        o.identification = ProductIdentification(condition_risk_level="high")
        o.liquidity = "unknown"
        score = compute_flip_score(o, WEIGHTS, BANKROLL_CFG)
        self.assertLess(score, 40)

    def test_score_bounded_0_100(self):
        o = _strong_opportunity()
        o.valuation.confidence_pct = 500  # malformed/out-of-range input
        score = compute_flip_score(o, WEIGHTS, BANKROLL_CFG)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)


class TestDecision(unittest.TestCase):
    def test_buy_decision(self):
        o = _strong_opportunity()
        o.flip_score = 90
        o.flip_score_band = "EXCELLENT"
        decision, reasons = decide(o, BANKROLL_CFG)
        self.assertEqual(decision, "BUY")

    def test_pass_below_profit_target(self):
        o = _strong_opportunity()
        o.expected_net_profit_low = 5  # below $10 minimum
        o.flip_score = 90
        o.flip_score_band = "EXCELLENT"
        decision, reasons = decide(o, BANKROLL_CFG)
        self.assertEqual(decision, "PASS")

    def test_profitable_but_capital_risk(self):
        o = _strong_opportunity()
        o.current_price = 450  # 90% of $500 bankroll
        o.max_buy_price = 460
        o.flip_score = 90
        o.flip_score_band = "EXCELLENT"
        decision, reasons = decide(o, BANKROLL_CFG)
        self.assertEqual(decision, "PROFITABLE BUT CAPITAL RISK")

    def test_missing_data_passes_safely(self):
        o = Opportunity(title="x", url="u", source="s", current_price=None)
        decision, reasons = decide(o, BANKROLL_CFG)
        self.assertEqual(decision, "PASS")

    def test_score_and_decide_integration(self):
        o = _strong_opportunity()
        score_and_decide(o, WEIGHTS, BANKROLL_CFG)
        self.assertIsNotNone(o.flip_score)
        self.assertIn(o.decision, ("BUY", "WATCH", "PASS", "PROFITABLE BUT CAPITAL RISK"))


if __name__ == "__main__":
    unittest.main()
