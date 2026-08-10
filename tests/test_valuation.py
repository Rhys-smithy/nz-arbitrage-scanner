import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest

from scanner.models import CostBreakdown, Opportunity, ResaleValuation
from scanner.valuation import (
    apply_valuation,
    build_costs,
    compute_bidding_room,
    compute_max_buy_price,
    compute_profit_and_roi,
)

COST_MODEL = {
    "buyer_premium_percent": 15.0,
    "gst_percent": 0.0,
    "selling_fee_percent": 9.0,
    "payment_fee_percent": 2.9,
    "shipping_flat": 15.0,
    "packaging_flat": 5.0,
    "repair_allowance_percent": 0.0,
    "negotiation_allowance_percent": 0.0,
}

BANKROLL_CFG = {
    "starting_bankroll": 500,
    "target_bankroll": 10000,
    "minimum_profit": 75,
    "minimum_roi_percent": 40,
    "maximum_single_purchase_percent": 40,
}


class TestCostBreakdown(unittest.TestCase):
    def test_build_costs_percentages(self):
        c = build_costs(200, COST_MODEL)
        self.assertEqual(c.purchase_price, 200)
        self.assertEqual(c.buyer_premium, 30.0)
        self.assertEqual(c.selling_fees, 18.0)
        self.assertAlmostEqual(c.payment_fees, 5.8)
        self.assertEqual(c.shipping, 15.0)
        self.assertEqual(c.packaging, 5.0)

    def test_build_costs_zero_purchase(self):
        c = build_costs(0, COST_MODEL)
        self.assertEqual(c.buyer_premium, 0.0)
        self.assertEqual(c.shipping, 15.0)  # flat costs still apply

    def test_build_costs_negative_purchase_clamped(self):
        c = build_costs(-50, COST_MODEL)
        self.assertEqual(c.purchase_price, 0.0)

    def test_total_and_total_excluding_purchase(self):
        c = CostBreakdown(purchase_price=100, buyer_premium=15, gst=0, selling_fees=9,
                           payment_fees=2.9, shipping=15, packaging=5)
        self.assertEqual(c.total_excluding_purchase, 46.9)
        self.assertEqual(c.total, 146.9)


class TestProfitROI(unittest.TestCase):
    def test_profit_and_roi_computed(self):
        o = Opportunity(title="x", url="u", source="s", current_price=150)
        o.costs = build_costs(150, COST_MODEL)
        o.valuation = ResaleValuation(quick_sale_low=280, quick_sale_high=310)
        compute_profit_and_roi(o)
        self.assertIsNotNone(o.expected_net_profit_low)
        self.assertGreater(o.expected_net_profit_low, 0)
        self.assertIsNotNone(o.roi_low_pct)

    def test_missing_price_no_crash(self):
        o = Opportunity(title="x", url="u", source="s", current_price=None)
        o.valuation = ResaleValuation(quick_sale_low=280)
        compute_profit_and_roi(o)  # must not raise
        self.assertIsNone(o.expected_net_profit_low)

    def test_missing_valuation_no_crash(self):
        o = Opportunity(title="x", url="u", source="s", current_price=100)
        o.costs = build_costs(100, COST_MODEL)
        compute_profit_and_roi(o)
        self.assertIsNone(o.expected_net_profit_low)


class TestMaxBuyPrice(unittest.TestCase):
    def test_basic_max_buy_price(self):
        # quick sale 325, costs excl purchase ~35, min profit 75 -> matches spec example roughly
        max_buy = compute_max_buy_price(
            quick_sale_value=325, costs_excluding_purchase=35, minimum_profit=75, minimum_roi_percent=0
        )
        self.assertAlmostEqual(max_buy, 325 - 35 - 75)

    def test_roi_cap_can_bind_tighter_than_profit_cap(self):
        max_buy = compute_max_buy_price(
            quick_sale_value=200, costs_excluding_purchase=20, minimum_profit=10, minimum_roi_percent=100
        )
        # ROI 100% requires profit == cost basis, much stricter than $10 min profit
        self.assertLess(max_buy, 200 - 20 - 10)

    def test_never_negative(self):
        max_buy = compute_max_buy_price(
            quick_sale_value=50, costs_excluding_purchase=40, minimum_profit=75, minimum_roi_percent=40
        )
        self.assertEqual(max_buy, 0.0)

    def test_none_quick_sale_value(self):
        self.assertEqual(compute_max_buy_price(None, 10, 5), 0.0)


class TestBiddingRoom(unittest.TestCase):
    def test_bidding_room_positive(self):
        self.assertEqual(compute_bidding_room(175, 210), 35.0)

    def test_bidding_room_negative_clamped_to_zero(self):
        self.assertEqual(compute_bidding_room(250, 210), 0.0)

    def test_bidding_room_missing_values(self):
        self.assertEqual(compute_bidding_room(None, 210), 0.0)
        self.assertEqual(compute_bidding_room(100, None), 0.0)


class TestApplyValuationPipeline(unittest.TestCase):
    def test_end_to_end(self):
        o = Opportunity(title="Nikon D90 bundle", url="u", source="Turners", current_price=165)
        o.valuation = ResaleValuation(quick_sale_low=280, quick_sale_high=310, normal=325, optimistic=375,
                                       confidence_pct=87)
        apply_valuation(o, COST_MODEL, BANKROLL_CFG)
        self.assertIsNotNone(o.max_buy_price)
        self.assertIsNotNone(o.expected_net_profit_low)
        self.assertGreaterEqual(o.max_buy_price, 0)
        self.assertIsNotNone(o.bidding_room)


if __name__ == "__main__":
    unittest.main()
