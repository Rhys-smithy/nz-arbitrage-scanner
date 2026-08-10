import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest

from scanner.product_id import detect_condition_risk
from scanner.liquidity import estimate_liquidity
from scanner.models import ComparableEvidence

RISK_PHRASES = ["untested", "for parts", "no charger", "no battery", "broken", "damaged"]


class TestConditionRisk(unittest.TestCase):
    def test_no_risk_phrases(self):
        level, matched = detect_condition_risk("Nikon D90 body, excellent condition", RISK_PHRASES)
        self.assertEqual(level, "low")
        self.assertEqual(matched, [])

    def test_single_risk_phrase(self):
        level, matched = detect_condition_risk("Sold as untested", RISK_PHRASES)
        self.assertEqual(level, "medium")
        self.assertEqual(matched, ["untested"])

    def test_multiple_risk_phrases(self):
        level, matched = detect_condition_risk("Untested, no charger, no battery included", RISK_PHRASES)
        self.assertEqual(level, "high")
        self.assertEqual(len(matched), 3)

    def test_empty_text(self):
        level, matched = detect_condition_risk("", RISK_PHRASES)
        self.assertEqual(level, "low")


class TestLiquidity(unittest.TestCase):
    def test_no_evidence_unknown(self):
        level, window = estimate_liquidity([])
        self.assertEqual(level, "unknown")

    def test_multiple_sold_high_liquidity(self):
        evidence = [
            ComparableEvidence("P", "M", "used", 100, "NZD", "s", "u", "2026-08-01", 0.9, True)
            for _ in range(3)
        ]
        level, window = estimate_liquidity(evidence)
        self.assertEqual(level, "HIGH")

    def test_asking_only_low_liquidity(self):
        evidence = [ComparableEvidence("P", "M", "used", 100, "NZD", "s", "u", "2026-08-01", 0.9, False)]
        level, window = estimate_liquidity(evidence)
        self.assertEqual(level, "LOW")


if __name__ == "__main__":
    unittest.main()
