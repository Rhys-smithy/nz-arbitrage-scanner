import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest

from scanner.bankroll import BankrollState, capital_concentration_pct, exceeds_concentration_limit

BANKROLL_CFG = {"maximum_single_purchase_percent": 40}


class TestConcentration(unittest.TestCase):
    def test_normal_case(self):
        self.assertEqual(capital_concentration_pct(100, 500), 20.0)

    def test_full_bankroll(self):
        self.assertEqual(capital_concentration_pct(500, 500), 100.0)

    def test_zero_cash_is_max_risk(self):
        self.assertEqual(capital_concentration_pct(50, 0), 100.0)

    def test_exceeds_limit_true(self):
        self.assertTrue(exceeds_concentration_limit(450, 500, BANKROLL_CFG))  # 90% > 40%

    def test_exceeds_limit_false(self):
        self.assertFalse(exceeds_concentration_limit(100, 500, BANKROLL_CFG))  # 20% <= 40%

    def test_spec_example_450_of_500(self):
        # From spec section 14: $450 purchase from $500 bankroll should be flagged
        self.assertTrue(exceeds_concentration_limit(450, 500, BANKROLL_CFG))


class TestBankrollProgress(unittest.TestCase):
    def test_progress_zero_at_start(self):
        b = BankrollState(starting_bankroll=500, target_bankroll=10000, available_cash=500)
        self.assertEqual(b.progress_pct, 0.0)

    def test_progress_partial(self):
        b = BankrollState(starting_bankroll=500, target_bankroll=10000, available_cash=1000)
        self.assertGreater(b.progress_pct, 0)
        self.assertLess(b.progress_pct, 100)

    def test_progress_clamped_at_100(self):
        b = BankrollState(starting_bankroll=500, target_bankroll=10000, available_cash=20000)
        self.assertEqual(b.progress_pct, 100.0)

    def test_progress_with_inventory_value(self):
        b = BankrollState(starting_bankroll=500, target_bankroll=10000, available_cash=100, inventory_value=400)
        self.assertEqual(b.progress_pct, 0.0)  # 500 total = starting, no progress yet


if __name__ == "__main__":
    unittest.main()
