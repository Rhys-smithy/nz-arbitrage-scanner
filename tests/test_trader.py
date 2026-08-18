import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from unittest import mock

from scanner.models import ComparableEvidence
from scanner.trader import trader_review

NOW = "2026-08-16T10:59:00+00:00"


def _evidence(price=300.0, similarity=0.9):
    return ComparableEvidence("P", "M", "used", price, "NZD", "TradeMe", "u", NOW, similarity, True)


class TestTraderReviewIdentificationConfidenceIndependence(unittest.TestCase):
    """Phase 4B.5 bug fix: model_identified_confidently must come from
    upstream product identification and stay independent of the Trader's
    own reject_valuation verdict -- it must never be hardcoded True on the
    fallback path or derived from reject_valuation on the adjusted path."""

    def test_no_api_key_fallback_uses_real_identification_confidence_true(self):
        valuation, verdict = trader_review(
            title="Item", price=100, researcher_result={}, evidence=[_evidence()],
            costs_excl_purchase=10, bankroll=500, api_key="",
            model_identified_confidently=True,
        )
        self.assertFalse(verdict["ran"])
        confident_conf = valuation.confidence_pct

        valuation_low, _ = trader_review(
            title="Item", price=100, researcher_result={}, evidence=[_evidence()],
            costs_excl_purchase=10, bankroll=500, api_key="",
            model_identified_confidently=False,
        )
        self.assertGreater(confident_conf, valuation_low.confidence_pct)

    def test_no_api_key_fallback_no_longer_hardcodes_true(self):
        # Before the fix, the fallback path hardcoded
        # model_identified_confidently=True regardless of what was passed.
        confident, _ = trader_review(
            title="Item", price=100, researcher_result={}, evidence=[_evidence()],
            costs_excl_purchase=10, bankroll=500, api_key="",
            model_identified_confidently=False,
        )
        unconfident_expected_lower = confident.confidence_pct
        confident2, _ = trader_review(
            title="Item", price=100, researcher_result={}, evidence=[_evidence()],
            costs_excl_purchase=10, bankroll=500, api_key="",
            model_identified_confidently=True,
        )
        self.assertGreater(confident2.confidence_pct, unconfident_expected_lower)

    def test_default_parameter_is_false_not_true(self):
        # Calling without the new kwarg (e.g. an old caller) must not
        # silently behave as if the product was confidently identified.
        valuation, _ = trader_review(
            title="Item", price=100, researcher_result={}, evidence=[_evidence()],
            costs_excl_purchase=10, bankroll=500, api_key="",
        )
        explicit_false, _ = trader_review(
            title="Item", price=100, researcher_result={}, evidence=[_evidence()],
            costs_excl_purchase=10, bankroll=500, api_key="",
            model_identified_confidently=False,
        )
        self.assertEqual(valuation.confidence_pct, explicit_false.confidence_pct)

    def _mock_anthropic_response(self, reject_valuation):
        resp = mock.Mock()
        resp.raise_for_status = mock.Mock()
        resp.json.return_value = {
            "content": [{
                "text": (
                    '{"reject_valuation": %s, "weak_evidence_indices": [], '
                    '"reasoning": "test", "liquidity_concern": false}'
                    % ("true" if reject_valuation else "false")
                )
            }]
        }
        return resp

    @mock.patch("scanner.trader.requests.post")
    def test_adjusted_path_independent_of_reject_valuation_when_confident(self, mock_post):
        # Product was confidently identified, but the Trader rejects the
        # deal on its merits (e.g. thin margin) -- model_identified_confidently
        # must still reflect the real (True) product-ID confidence, not flip
        # to False just because the Trader didn't like the deal.
        mock_post.return_value = self._mock_anthropic_response(reject_valuation=True)
        valuation, verdict = trader_review(
            title="Item", price=100, researcher_result={"evidence_summary": "s", "uncertainty": "low"},
            evidence=[_evidence(), _evidence(310)], costs_excl_purchase=10, bankroll=500,
            api_key="fake-key", model_identified_confidently=True,
        )
        self.assertTrue(verdict["ran"])
        self.assertTrue(verdict["reject_valuation"])

        # Compare against the True-identification, non-rejected case: if
        # model_identified_confidently were still (bug) derived from
        # `not reject_valuation`, this rejected-but-confident case would
        # show LOWER confidence than an accepted-but-unconfident case below.
        mock_post.return_value = self._mock_anthropic_response(reject_valuation=False)
        unconfident_accepted, verdict2 = trader_review(
            title="Item", price=100, researcher_result={"evidence_summary": "s", "uncertainty": "low"},
            evidence=[_evidence(), _evidence(310)], costs_excl_purchase=10, bankroll=500,
            api_key="fake-key", model_identified_confidently=False,
        )
        self.assertFalse(verdict2["reject_valuation"])

        # Confident-but-rejected must score >= unconfident-but-accepted on
        # the model_factor component -- i.e. reject_valuation is no longer
        # driving this number.
        self.assertGreaterEqual(valuation.confidence_pct, unconfident_accepted.confidence_pct)

    @mock.patch("scanner.trader.requests.post")
    def test_adjusted_path_passes_through_false_even_when_accepted(self, mock_post):
        mock_post.return_value = self._mock_anthropic_response(reject_valuation=False)
        confident, _ = trader_review(
            title="Item", price=100, researcher_result={"evidence_summary": "s", "uncertainty": "low"},
            evidence=[_evidence(), _evidence(310)], costs_excl_purchase=10, bankroll=500,
            api_key="fake-key", model_identified_confidently=True,
        )
        mock_post.return_value = self._mock_anthropic_response(reject_valuation=False)
        unconfident, _ = trader_review(
            title="Item", price=100, researcher_result={"evidence_summary": "s", "uncertainty": "low"},
            evidence=[_evidence(), _evidence(310)], costs_excl_purchase=10, bankroll=500,
            api_key="fake-key", model_identified_confidently=False,
        )
        # Same reject_valuation (False) both times -- the only difference
        # is model_identified_confidently, so confidence must differ.
        self.assertGreater(confident.confidence_pct, unconfident.confidence_pct)


if __name__ == "__main__":
    unittest.main()
