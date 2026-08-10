import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest

from scanner.search.base import SearchResult
from scanner.search.util import canonicalize_url, dedupe_results, identify_marketplace


class TestCanonicalizeUrl(unittest.TestCase):
    def test_strips_tracking_params(self):
        url = "https://www.trademe.co.nz/a/listing-1?utm_source=fb&utm_campaign=x"
        self.assertEqual(canonicalize_url(url), "https://www.trademe.co.nz/a/listing-1")

    def test_http_and_https_equivalent(self):
        self.assertEqual(canonicalize_url("http://example.com/x"), canonicalize_url("https://example.com/x"))

    def test_lowercases_host(self):
        self.assertEqual(canonicalize_url("https://EXAMPLE.com/x"), canonicalize_url("https://example.com/x"))

    def test_strips_trailing_slash(self):
        self.assertEqual(canonicalize_url("https://example.com/x/"), canonicalize_url("https://example.com/x"))

    def test_strips_fragment(self):
        self.assertEqual(canonicalize_url("https://example.com/x#section"), canonicalize_url("https://example.com/x"))

    def test_keeps_meaningful_query_params(self):
        self.assertNotEqual(
            canonicalize_url("https://example.com/x?id=1"),
            canonicalize_url("https://example.com/x?id=2"),
        )

    def test_empty_url(self):
        self.assertEqual(canonicalize_url(""), "")


class TestIdentifyMarketplace(unittest.TestCase):
    def test_trademe(self):
        self.assertEqual(identify_marketplace("https://www.trademe.co.nz/a/x"), "Trade Me")

    def test_ebay_au(self):
        self.assertEqual(identify_marketplace("https://www.ebay.com.au/itm/x"), "eBay AU")

    def test_unknown_domain(self):
        self.assertEqual(identify_marketplace("https://randomsite.example/x"), "randomsite.example")

    def test_empty_url(self):
        self.assertEqual(identify_marketplace(""), "unknown")


class TestDedupeResults(unittest.TestCase):
    def _result(self, url, title="x"):
        return SearchResult(title=title, url=url, price=None, currency="NZD", source="s")

    def test_dedupes_identical_urls(self):
        results = [self._result("https://a.com/x"), self._result("https://a.com/x")]
        self.assertEqual(len(dedupe_results(results)), 1)

    def test_dedupes_tracking_param_variants(self):
        results = [
            self._result("https://a.com/x?utm_source=fb"),
            self._result("https://a.com/x?utm_source=twitter"),
        ]
        self.assertEqual(len(dedupe_results(results)), 1)

    def test_keeps_distinct_urls(self):
        results = [self._result("https://a.com/x"), self._result("https://a.com/y")]
        self.assertEqual(len(dedupe_results(results)), 2)

    def test_keeps_first_occurrence(self):
        first = self._result("https://a.com/x", title="first")
        second = self._result("https://a.com/x", title="second")
        deduped = dedupe_results([first, second])
        self.assertEqual(deduped[0].title, "first")


if __name__ == "__main__":
    unittest.main()
