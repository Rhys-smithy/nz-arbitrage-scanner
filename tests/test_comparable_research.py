import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from unittest import mock

from scanner.comparable_research import (
    build_comparables_from_search_results,
    extract_price,
    research_comparables,
)
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


if __name__ == "__main__":
    unittest.main()
