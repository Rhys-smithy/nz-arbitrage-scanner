import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from unittest import mock

from scanner.discover import DEFAULT_DISCOVERY_DOMAINS, _process_query_results, run_discovery
from scanner.search.base import SearchResult


def _result(url, title="Item", price=None):
    return SearchResult(title=title, url=url, price=price, currency="NZD", source="web_search:tavily")


class TestDefaultDiscoveryDomains(unittest.TestCase):
    def test_no_ebay_in_default_domains(self):
        for domain in DEFAULT_DISCOVERY_DOMAINS:
            self.assertNotIn("ebay", domain.lower())

    def test_default_domains_are_the_known_nz_marketplaces(self):
        self.assertEqual(
            set(DEFAULT_DISCOVERY_DOMAINS),
            {"trademe.co.nz", "turners.co.nz", "thorntons.net.nz", "mainlandauctions.nz"},
        )


class TestProcessQueryResults(unittest.TestCase):
    def test_counts_raw_unique_valid_and_rejections(self):
        results = [
            _result("https://www.trademe.co.nz/a/marketplace/listing/12345"),  # valid individual listing
            _result("https://www.trademe.co.nz/a/marketplace/search"),         # category/search page
            _result("https://www.trademe.co.nz/a/marketplace/listing/12345"),  # duplicate of first
        ]
        seen = set()
        entry, unique_results = _process_query_results("query text", ["trademe.co.nz"], results, seen)

        self.assertEqual(entry["query"], "query text")
        self.assertEqual(entry["domains"], ["trademe.co.nz"])
        self.assertEqual(entry["raw_results"], 3)
        self.assertEqual(entry["unique_results"], 2)
        self.assertEqual(entry["valid_individual_listings"], 1)
        self.assertEqual(entry["rejected_duplicate"], 1)
        self.assertEqual(entry["rejected_not_individual_listing"], 1)
        self.assertEqual(len(unique_results), 2)

    def test_seen_set_persists_duplicates_across_calls(self):
        seen = set()
        entry1, _ = _process_query_results(
            "q1", [], [_result("https://www.trademe.co.nz/a/marketplace/listing/1")], seen
        )
        entry2, _ = _process_query_results(
            "q2", [], [_result("https://www.trademe.co.nz/a/marketplace/listing/1")], seen
        )
        self.assertEqual(entry1["unique_results"], 1)
        self.assertEqual(entry2["unique_results"], 0)
        self.assertEqual(entry2["rejected_duplicate"], 1)

    def test_empty_results_gives_zeroed_entry(self):
        entry, unique_results = _process_query_results("q", ["trademe.co.nz"], [], set())
        self.assertEqual(entry["raw_results"], 0)
        self.assertEqual(entry["unique_results"], 0)
        self.assertEqual(entry["valid_individual_listings"], 0)
        self.assertEqual(unique_results, [])


class _RunDiscoveryTestBase(unittest.TestCase):
    """Shared setup mocking out everything downstream of the search loop
    (product ID, comparable research, valuation) -- these tests only care
    about query allocation and domain filtering, which is exercised fully
    as long as the search loop runs and no candidates survive to the
    (expensive, separately-tested) valuation stage below it."""

    def _config(self, max_queries=5, products=None, include_domains=None):
        cfg = {
            "discovery": {
                "enabled": True,
                "max_queries_per_run": max_queries,
                "max_results_per_query": 8,
                "max_research_items": 5,
                "products": products or ["Nintendo Switch", "GoPro"],
            },
            "query_generation": {"concepts": ["bundle"]},
        }
        if include_domains is not None:
            cfg["discovery"]["include_domains"] = include_domains
        return cfg

    def setUp(self):
        patches = [
            mock.patch("scanner.discover.save_stats"),
            mock.patch("scanner.discover.load_stats", return_value={}),
            mock.patch("scanner.discover.save_discovered"),
            mock.patch("scanner.discover.load_discovered", return_value={}),
            mock.patch("scanner.discover.WebSearchSource"),
        ]
        self.mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.mock_source_cls = self.mocks[-1]
        self.mock_source = self.mock_source_cls.return_value
        self.mock_source.available = True
        self.mock_source.search.return_value = []  # no results -> no candidates reach valuation


class TestRunDiscoveryUsesIncludeDomains(_RunDiscoveryTestBase):
    def test_default_domains_passed_to_every_search_call(self):
        result = run_discovery(self._config())
        self.assertEqual(result, [])
        self.assertTrue(self.mock_source.search.called)
        for call in self.mock_source.search.call_args_list:
            self.assertEqual(call.kwargs.get("include_domains"), DEFAULT_DISCOVERY_DOMAINS)


class TestRunDiscoveryExcludesEbay(_RunDiscoveryTestBase):
    def test_ebay_stripped_even_when_configured(self):
        cfg = self._config(include_domains=["trademe.co.nz", "ebay.com.au", "EBAY.COM", "www.ebay.com"])
        run_discovery(cfg)

        self.assertTrue(self.mock_source.search.called)
        for call in self.mock_source.search.call_args_list:
            domains = call.kwargs.get("include_domains")
            self.assertIn("trademe.co.nz", domains)
            for ebay_domain in domains:
                self.assertNotIn("ebay", ebay_domain.lower())


class TestRunDiscoveryDistributesQueryBudget(_RunDiscoveryTestBase):
    def test_every_configured_product_is_queried(self):
        products = ["Nintendo Switch", "GoPro", "Makita tools"]
        run_discovery(self._config(max_queries=6, products=products))

        queried_products = set()
        for call in self.mock_source.search.call_args_list:
            query = call.args[0]
            for product in products:
                if product in query:
                    queried_products.add(product)
        self.assertEqual(queried_products, set(products))


if __name__ == "__main__":
    unittest.main()
