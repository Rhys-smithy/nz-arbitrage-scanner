import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from datetime import datetime, timezone

from scanner.comparables import MIN_COMPARABLE_SIMILARITY, build_valuation_from_evidence, compute_confidence
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


class TestMinSimilarityFiltering(unittest.TestCase):
    """Phase 4B.5 (Run #37/#38 instability fix): a comparable's price must
    not be able to set quick_sale_low/high/normal/optimistic or feed
    confidence unless it's similar enough to the listing to trust for
    pricing -- similarity is still recorded and shown on val.evidence for a
    human to inspect either way."""

    def test_low_similarity_cheap_outlier_cannot_set_valuation_floor(self):
        good = [_evidence(300, similarity=0.9), _evidence(320, similarity=0.85)]
        outlier = _evidence(1, similarity=0.05)  # e.g. an unrelated $1 page
        val = build_valuation_from_evidence(good + [outlier], True)
        self.assertGreater(val.quick_sale_low, 100)  # not dragged to ~$0.90
        self.assertEqual(val.quick_sale_low, round(300 * 0.9, 2))

    def test_low_similarity_outlier_still_preserved_in_full_evidence(self):
        good = [_evidence(300, similarity=0.9)]
        outlier = _evidence(1, similarity=0.05)
        val = build_valuation_from_evidence(good + [outlier], True)
        self.assertEqual(len(val.evidence), 2)
        self.assertIn(outlier, val.evidence)

    def test_all_evidence_below_threshold_gives_distinct_insufficient_note(self):
        weak = [_evidence(300, similarity=0.1), _evidence(50, similarity=0.2)]
        val = build_valuation_from_evidence(weak, True)
        self.assertIsNone(val.quick_sale_low)
        self.assertEqual(val.confidence_pct, 0.0)
        self.assertIn("minimum similarity threshold", val.evidence_note)
        # Distinct from the plain no-evidence-at-all case.
        self.assertNotEqual(val.evidence_note, "Insufficient comparable evidence.")
        # Evidence itself is still preserved, just excluded from the numbers.
        self.assertEqual(len(val.evidence), 2)

    def test_boundary_similarity_exactly_at_threshold_is_accepted(self):
        val = build_valuation_from_evidence(
            [_evidence(300, similarity=MIN_COMPARABLE_SIMILARITY)], True
        )
        self.assertEqual(val.quick_sale_low, round(300 * 0.9, 2))

    def test_just_below_boundary_is_excluded(self):
        val = build_valuation_from_evidence(
            [_evidence(300, similarity=MIN_COMPARABLE_SIMILARITY - 0.01)], True
        )
        self.assertIsNone(val.quick_sale_low)


class TestRun37Run38RegressionRealEvidence(unittest.TestCase):
    """Regression coverage built directly from the persisted evidence in
    reports/discovery_20260816_1010.json (Run #37) and
    reports/discovery_20260816_1059.json (Run #38) -- the same evidence
    that produced the WATCH/PASS flip-flops the fix targets. Locks in that
    quick_sale_low now lands in a stable, sane range for both runs instead
    of swinging 13-56x on a single low-similarity comparable."""

    def _ev(self, price, similarity, is_sold=False, source="web"):
        return ComparableEvidence("P", "", "unknown", price, "NZD", source, "u", NOW, similarity, is_sold)

    def test_fuji_c325_stable_or_honestly_insufficient_across_runs(self):
        # Run #37 (10:10): best comp was $1396 at similarity 0.222; the
        # floor was a $820 eBay AU "sold" comp at similarity 0.071.
        run37 = [
            self._ev(1396.0, 0.222), self._ev(1396.0, 0.182),
            self._ev(999.0, 0.077), self._ev(869.0, 0.091),
            self._ev(820.0, 0.071, is_sold=True), self._ev(1115.41, 0.071),
        ]
        # Run #38 (10:59): same-shape evidence plus a stray $1 Turners page
        # at similarity 0.083 that used to set quick_sale_low to $0.90.
        run38 = [
            self._ev(1.0, 0.083, source="Turners"),
            self._ev(1396.0, 0.222), self._ev(1396.0, 0.222),
            self._ev(999.0, 0.077), self._ev(869.0, 0.091),
            self._ev(544.25, 0.167), self._ev(1115.41, 0.083),
            self._ev(464.2, 0.083), self._ev(999.98, 0.083),
        ]
        val37 = build_valuation_from_evidence(run37, True)
        val38 = build_valuation_from_evidence(run38, True)
        # Neither run's evidence clears MIN_COMPARABLE_SIMILARITY (best is
        # 0.222) -- both should now honestly report insufficient evidence
        # instead of the $738 vs $0.90 split they produced before the fix.
        self.assertIsNone(val37.quick_sale_low)
        self.assertIsNone(val38.quick_sale_low)
        self.assertIn("minimum similarity threshold", val37.evidence_note)
        self.assertIn("minimum similarity threshold", val38.evidence_note)

    def test_yzf_r3a_stable_across_runs(self):
        # Run #37 (10:10): floor was a genuine $3150 KBB value page (0.333).
        run37 = [
            self._ev(4990.0, 0.6), self._ev(4000.0, 0.429), self._ev(4199.0, 0.429),
            self._ev(3150.0, 0.333), self._ev(4990.0, 0.375), self._ev(4990.0, 0.6),
            self._ev(3150.0, 0.333), self._ev(4000.0, 0.429), self._ev(4990.0, 0.375),
            self._ev(3150.0, 0.333),
        ]
        # Run #38 (10:59): same-shape evidence plus a $56 Trade Me listing
        # at similarity 0.143 (almost certainly a parts listing, not the
        # bike) that used to set quick_sale_low to $50.40.
        run38 = [
            self._ev(4990.0, 0.429), self._ev(4000.0, 0.429), self._ev(3990.0, 0.429),
            self._ev(4199.0, 0.3), self._ev(4990.0, 0.6), self._ev(4990.0, 0.6),
            self._ev(4990.0, 0.375), self._ev(4000.0, 0.429), self._ev(5000.0, 0.333),
            self._ev(56.0, 0.143), self._ev(8499.0, 0.5), self._ev(57.0, 0.167),
        ]
        val37 = build_valuation_from_evidence(run37, True)
        val38 = build_valuation_from_evidence(run38, True)
        self.assertIsNotNone(val37.quick_sale_low)
        self.assertIsNotNone(val38.quick_sale_low)
        # Both floors now sit in the same plausible thousands-of-dollars
        # range for a real motorbike, not $2835 vs $50.40.
        self.assertGreater(val37.quick_sale_low, 2000)
        self.assertGreater(val38.quick_sale_low, 2000)
        # And they're within a sane multiple of each other (was 56x apart).
        ratio = max(val37.quick_sale_low, val38.quick_sale_low) / min(
            val37.quick_sale_low, val38.quick_sale_low
        )
        self.assertLess(ratio, 2.0)


if __name__ == "__main__":
    unittest.main()
