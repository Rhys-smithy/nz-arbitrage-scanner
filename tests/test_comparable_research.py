import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from unittest import mock

from scanner.comparable_research import (
    build_comparables_from_search_results,
    extract_price,
    extract_price_with_currency,
    research_comparables,
)
from scanner.comparables import build_valuation_from_evidence
from scanner.search.base import SearchResult


class TestExtractPrice(unittest.TestCase):
    def test_dollar_sign_price(self):
        self.assertEqual(extract_price("Selling for $180 firm"), 180.0)

    def test_nz_dollar_prefix(self):
        self.assertEqual(extract_price("NZ$1,250 or best offer"), 1250.0)

    def test_no_price_in_text(self):
        self.assertIsNone(extract_price("no price mentioned here"))

    def test_empty_text(self):
        self.assertIsNone(extract_price(""))

    def test_decimal_price(self):
        self.assertEqual(extract_price("Buy now $99.95"), 99.95)


class TestBuildComparablesFromSearchResults(unittest.TestCase):
    def test_skips_results_with_no_extractable_price(self):
        results = [SearchResult(title="No price here", url="https://a.com/x", price=None,
                                 currency="NZD", source="s", description="nothing useful")]
        evidence = build_comparables_from_search_results("Product", results)
        self.assertEqual(evidence, [])

    def test_uses_structured_price_when_present(self):
        results = [SearchResult(title="x", url="https://trademe.co.nz/x", price=250, currency="NZD", source="s")]
        evidence = build_comparables_from_search_results("Product", results)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].price, 250)

    def test_extracts_price_from_text_when_missing(self):
        results = [SearchResult(title="Selling for $200", url="https://trademe.co.nz/x", price=None,
                                 currency="NZD", source="s")]
        evidence = build_comparables_from_search_results("Product", results)
        self.assertEqual(evidence[0].price, 200)

    def test_classifies_evidence_type(self):
        results = [SearchResult(title="x $200", url="https://www.noelleeming.co.nz/x", price=None,
                                 currency="NZD", source="s")]
        evidence = build_comparables_from_search_results("Product", results)
        self.assertEqual(evidence[0].evidence_type, "RETAIL")


class TestResearchComparables(unittest.TestCase):
    def test_unavailable_source_returns_empty(self):
        source = mock.Mock()
        source.available = False
        self.assertEqual(research_comparables("Product", source), [])

    def test_excludes_own_url_from_evidence(self):
        own_url = "https://trademe.co.nz/a/self-listing"
        other_result = SearchResult(title="x $200", url="https://trademe.co.nz/a/other", price=200,
                                     currency="NZD", source="s")
        self_result = SearchResult(title="x $180", url=own_url, price=180, currency="NZD", source="s")

        source = mock.Mock()
        source.available = True
        source.search.return_value = [other_result, self_result]

        evidence = research_comparables("Product", source, exclude_url=own_url)
        urls = [e.url for e in evidence]
        self.assertNotIn(own_url, urls)
        self.assertIn(other_result.url, urls)


class TestExtractPriceWithCurrency(unittest.TestCase):
    def test_bare_dollar_is_ambiguous(self):
        price, currency = extract_price_with_currency("Selling for $180 firm")
        self.assertEqual(price, 180.0)
        self.assertIsNone(currency)

    def test_us_dollar_prefix_is_explicit(self):
        price, currency = extract_price_with_currency("US$4,199 or best offer")
        self.assertEqual(price, 4199.0)
        self.assertEqual(currency, "USD")

    def test_nz_dollar_prefix_is_explicit(self):
        price, currency = extract_price_with_currency("NZ$1,250 or best offer")
        self.assertEqual(price, 1250.0)
        self.assertEqual(currency, "NZD")

    def test_pound_symbol_is_explicit(self):
        price, currency = extract_price_with_currency("£120 collection only")
        self.assertEqual(price, 120.0)
        self.assertEqual(currency, "GBP")

    def test_no_price_returns_none(self):
        self.assertIsNone(extract_price_with_currency("no price mentioned here"))


class TestCurrencyDetermination(unittest.TestCase):
    """Covers the Phase 4B.6 currency-correctness fix: provider output must
    no longer blindly force NZD, domain/text inference must actually run,
    and a genuinely unresolvable currency must never be treated as NZD."""

    def test_usd_result_converts_correctly_to_nzd(self):
        # No structured price/currency from the provider (the realistic
        # case for Tavily/Brave/SerpAPI -- see scanner/search/providers/*.py)
        # -- domain inference (kbb.com is a known US business) plus text
        # extraction supply the raw amount and the correct USD currency.
        results = [SearchResult(
            title="2016 Yamaha YZF-R3 Value", url="https://www.kbb.com/motorcycles/yamaha/yzf-r3/2016",
            price=None, currency="", source="web_search:tavily", description="Typical price $3,150",
        )]
        evidence = build_comparables_from_search_results("2016 Yamaha YZF-R3A", results)
        self.assertEqual(len(evidence), 1)
        # 3150 USD * 1.66 (scanner/evidence.py's static USD rate) = 5229.0
        self.assertEqual(evidence[0].price, 5229.0)
        self.assertEqual(evidence[0].currency, "NZD")
        self.assertEqual(evidence[0].original_price, 3150.0)
        self.assertEqual(evidence[0].original_currency, "USD")

    def test_aud_result_converts_correctly_to_nzd(self):
        results = [SearchResult(
            title="Brateck Projector Ceiling Mount", url="https://www.mediaform.com.au/brateck-projector-ceiling-mount",
            price=None, currency="", source="web_search:tavily", description="$96.46",
        )]
        evidence = build_comparables_from_search_results("Brateck Projector Ceiling Mount", results)
        self.assertEqual(len(evidence), 1)
        # 96.46 AUD * 1.09 = 105.1414 -> rounded 105.14
        self.assertEqual(evidence[0].price, 105.14)
        self.assertEqual(evidence[0].currency, "NZD")
        self.assertEqual(evidence[0].original_currency, "AUD")

    def test_nzd_remains_unchanged(self):
        results = [SearchResult(
            title="Yamaha AG125", url="https://www.trademe.co.nz/a/motors/x",
            price=1850, currency="NZD", source="s",
        )]
        evidence = build_comparables_from_search_results("Yamaha AG125", results)
        self.assertEqual(evidence[0].price, 1850)
        self.assertEqual(evidence[0].currency, "NZD")
        # NZD is never "converted" -- original_price/original_currency stay unset.
        self.assertIsNone(evidence[0].original_price)
        self.assertIsNone(evidence[0].original_currency)

    def test_explicit_source_currency_takes_precedence_over_domain(self):
        # A source that *does* legitimately know its own currency (e.g. a
        # future structured provider) must win over domain inference, even
        # when the domain would otherwise suggest something else.
        results = [SearchResult(
            title="x", url="https://www.trademe.co.nz/a/x", price=100, currency="USD", source="s",
        )]
        evidence = build_comparables_from_search_results("Product", results)
        self.assertEqual(evidence[0].original_currency, "USD")
        self.assertEqual(evidence[0].price, 166.0)  # 100 * 1.66

    def test_domain_inference_used_when_provider_currency_absent(self):
        # Provider currency is "" (falsy, the current real behaviour of
        # every provider since none has a structured currency field) --
        # must fall through to domain inference, not default to NZD.
        results = [SearchResult(
            title="x", url="https://www.cycletrader.com/2016-Yamaha-Yzf-R3",
            price=4000, currency="", source="web_search:tavily",
        )]
        evidence = build_comparables_from_search_results("2016 Yamaha YZF-R3A", results)
        self.assertEqual(evidence[0].original_currency, "USD")
        self.assertEqual(evidence[0].price, 6640.0)  # 4000 * 1.66

    def test_text_currency_symbol_beats_domain_inference(self):
        # An explicit "US$" in the result's own text is a stronger signal
        # than domain inference and must be used even on a domain with no
        # recognised currency of its own.
        results = [SearchResult(
            title="x", url="https://redmondusedmotorcycles.com/x",
            price=None, currency="", source="web_search:tavily", description="US$4,199 firm",
        )]
        evidence = build_comparables_from_search_results("2016 Yamaha YZF-R3A", results)
        self.assertEqual(evidence[0].original_currency, "USD")
        self.assertEqual(evidence[0].price, 6970.34)  # 4199 * 1.66

    def test_unknown_currency_does_not_become_nzd(self):
        # Unrecognised domain, no explicit source currency, bare "$" in
        # text (ambiguous) -- must not silently become NZD.
        results = [SearchResult(
            title="x", url="https://randomshop.example.com/x",
            price=None, currency="", source="web_search:tavily", description="$500 obo",
        )]
        evidence = build_comparables_from_search_results("Product", results)
        self.assertEqual(len(evidence), 1)  # still visible, never hidden
        self.assertIsNone(evidence[0].price)  # never an unverified NZD number
        self.assertEqual(evidence[0].currency, "unknown")
        self.assertEqual(evidence[0].original_price, 500.0)  # raw value preserved for inspection

    def test_unknown_currency_evidence_never_enters_valuation(self):
        # Confirms exclusion from calculations end-to-end, not just at the
        # ComparableEvidence-construction level: an unknown-currency item
        # must never appear in comparables.py's qualified/priced set, even
        # at high title similarity.
        results = [SearchResult(
            title="2016 Yamaha YZF-R3A", url="https://randomshop.example.com/x",
            price=None, currency="", source="web_search:tavily", description="$5000 firm",
        )]
        evidence = build_comparables_from_search_results("2016 Yamaha YZF-R3A", results)
        self.assertEqual(evidence[0].similarity_score, 1.0)  # would otherwise easily qualify
        val = build_valuation_from_evidence(evidence, model_identified_confidently=True)
        self.assertIsNone(val.quick_sale_low)
        self.assertIn("Insufficient comparable evidence", val.evidence_note)

    def test_liquidity_unaffected_by_unknown_currency_evidence(self):
        # scanner/liquidity.py's estimate_liquidity() only looks at
        # is_sold/count -- never price/currency -- so it must return the
        # same result whether or not currency was resolvable.
        from scanner.liquidity import estimate_liquidity
        results = [SearchResult(
            title="2016 Yamaha YZF-R3A", url="https://randomshop.example.com/x",
            price=None, currency="", source="web_search:tavily", description="$5000 firm", is_sold=False,
        )]
        evidence = build_comparables_from_search_results("2016 Yamaha YZF-R3A", results)
        self.assertEqual(evidence[0].price, None)
        level, window = estimate_liquidity(evidence)
        self.assertEqual((level, window), ("LOW", "1-3 months"))  # non-empty evidence, 0 sold


class TestYZFR3ACurrencyRegression(unittest.TestCase):
    """Phase 4B.6 regression: the real Run #37 (reports/discovery_
    20260816_1010.json) evidence for "2016 Yamaha YZF-R3A" included seven
    US-sourced comparables (motorcycle.com, cycletrader.com, kbb.com,
    jdpower.com) that were all silently priced as NZD before this fix
    (every search provider hardcoded currency="NZD"). This reproduces that
    real evidence as raw SearchResults (as Tavily would actually have
    returned them: price=None, currency="", bare "$" in text) and checks
    the corrected valuation is materially different from -- and higher
    than -- the old, uncorrected numbers persisted in that report."""

    def _build(self, url, price, similarity_title):
        return SearchResult(
            title=similarity_title, url=url, price=None, currency="",
            source="web_search:tavily", description=f"${price:,.2f}",
        )

    def test_corrected_valuation_differs_materially_from_old_run37_numbers(self):
        title = "2016 Yamaha YZF-R3A"
        results = [
            self._build("https://www.motorcycle.com/specs/yamaha/sport/2016/yzf/r3/detail.html", 4990.0, title),
            self._build("https://www.motorcycle.com/specs/yamaha/sport/2016/yzf/r3/detail.html", 4990.0, title),
            self._build("https://www.cycletrader.com/2016-Yamaha-Yzf-R3/x", 4000.0, title),
            self._build("https://redmondusedmotorcycles.com/products/2016-yamaha-yzf-r3", 4199.0, title),
            self._build("https://www.cycletrader.com/2016-Yamaha-Yzf-R3/x", 4000.0, title),
            self._build("https://www.jdpower.com/motorcycles/2016/yamaha/yzf-r3-321cc/values", 4990.0, title),
            self._build("https://ridermagazine.com/2017/01/24/2016-yamaha-yzf-r3-rider-tour-test", 4990.0, title),
            self._build("https://www.kbb.com/motorcycles/yamaha/yzf-r3/2016", 3150.0, title),
            self._build("https://www.kbb.com/motorcycles/yamaha/yzf-r3/2016", 3150.0, title),
            self._build("https://www.kbb.com/motorcycles/yamaha/yzf-r3/2016", 3150.0, title),
        ]

        evidence = build_comparables_from_search_results(title, results)
        self.assertEqual(len(evidence), 10)

        # OLD (pre-fix) behaviour: every provider hardcoded currency="NZD",
        # so these raw US-dollar amounts were used as-is. That's exactly
        # what the real persisted Run #37 report shows: quick_sale_low
        # 2835.0, normal 4099.5, optimistic 4990.0.
        from scanner.models import ComparableEvidence as CE
        old_ce = [
            CE(product=title, model="", condition="unknown", price=p, currency="NZD", source="x",
               url="u", date_observed="", similarity_score=e.similarity_score, is_sold=False)
            for e, p in zip(evidence, [4990.0, 4990.0, 4000.0, 4199.0, 4000.0, 4990.0, 4990.0, 3150.0, 3150.0, 3150.0])
        ]
        old_val = build_valuation_from_evidence(old_ce, model_identified_confidently=True)
        self.assertEqual(old_val.quick_sale_low, 2835.0)
        self.assertEqual(old_val.normal, 4099.5)
        self.assertEqual(old_val.optimistic, 4990.0)

        # NEW (corrected) behaviour: same raw evidence, currency now
        # correctly resolved to USD (kbb.com/jdpower.com/cycletrader.com/
        # motorcycle.com are known businesses; redmondusedmotorcycles.com/
        # ridermagazine.com fall back to text -- there is none here beyond
        # a bare "$", so those two entries are excluded as unknown-currency
        # rather than guessed, which is itself part of the fix's intended,
        # documented behaviour).
        new_val = build_valuation_from_evidence(evidence, model_identified_confidently=True)

        self.assertIsNotNone(new_val.quick_sale_low)
        self.assertNotEqual(new_val.quick_sale_low, old_val.quick_sale_low)
        self.assertNotEqual(new_val.normal, old_val.normal)
        self.assertNotEqual(new_val.optimistic, old_val.optimistic)

        # Material and directional: correcting USD->NZD raises the figures
        # (NZD is weaker than USD), it doesn't just wobble them.
        self.assertGreater(new_val.quick_sale_low, old_val.quick_sale_low * 1.3)
        self.assertGreater(new_val.optimistic, old_val.optimistic * 1.3)


if __name__ == "__main__":
    unittest.main()
