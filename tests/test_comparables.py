import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from datetime import datetime, timezone

from scanner.comparables import build_valuation_from_evidence, compute_confidence
from scanner.models import ComparableEvidence

NOW = datetime.now(timezone.utc).isoformat()


def _evidence(price, is_sold=True, similarity=0.9, date=NOW):
    return ComparableEvidence("P", "M", "used", price, "NZD", "TradeMe", "u", date, similarity, is_sold)


class TestConfidence(unittest.TestCase):
    def test_no_evidence_zero_confidence(self):
        self.assertEqual(compute_confidence([], True), 0.0)

    def test_more_evidence_higher_confidence(self):
        c1 = compute_confidence([_evidence(100)], True)
        c2 = compute_confidence([_evidence(100), _evidence(105), _evidence(110), _evidence(108)], True)
        self.assertGreater(c2, c1)

    def test_unidentified_model_lowers_confidence(self):
        evidence = [_evidence(100), _evidence(105)]
        confident = compute_confidence(evidence, True)
        unconfident = compute_confidence(evidence, False)
        self.assertGreater(confident, unconfident)

    def test_wide_price_spread_lowers_confidence(self):
        tight = compute_confidence([_evidence(100), _evidence(105)], True)
        wide = compute_confidence([_evidence(50), _evidence(500)], True)
        self.assertGreater(tight, wide)

    def test_old_evidence_lowers_confidence(self):
        recent = compute_confidence([_evidence(100, date=NOW), _evidence(105, date=NOW)], True)
        old = compute_confidence(
            [_evidence(100, date="2020-01-01T00:00:00+00:00"), _evidence(105, date="2020-01-01T00:00:00+00:00")],
            True,
        )
        self.assertGreater(recent, old)


class TestBuildValuation(unittest.TestCase):
    def test_empty_evidence_gives_insufficient_note(self):
        val = build_valuation_from_evidence([], True)
        self.assertEqual(val.evidence_note, "Insufficient comparable evidence.")
        self.assertIsNone(val.quick_sale_low)

    def test_valuation_ordering(self):
        val = build_valuation_from_evidence([_evidence(280), _evidence(300), _evidence(325)], True)
        self.assertLessEqual(val.quick_sale_low, val.quick_sale_high)
        self.assertLessEqual(val.normal, val.optimistic)

    def test_asking_only_prices_still_produce_valuation_but_lower_confidence(self):
        sold = build_valuation_from_evidence([_evidence(300, is_sold=True), _evidence(310, is_sold=True)], True)
        asking = build_valuation_from_evidence([_evidence(300, is_sold=False), _evidence(310, is_sold=False)], True)
        self.assertGreaterEqual(sold.confidence_pct, asking.confidence_pct)


if __name__ == "__main__":
    unittest.main()
