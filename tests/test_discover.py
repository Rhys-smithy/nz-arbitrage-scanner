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

    def test_ebay_result_rejected_even_though_it_matches_listing_pattern(self):
        # Regression test (PR #5 review): identify_marketplace()/
        # is_individual_listing_url() still recognise eBay listing URLs as
        # valid (that logic is shared with comparable_research.py, which
        # legitimately wants eBay evidence) -- so without an explicit eBay
        # check in _process_query_results, this URL would previously have
        # counted as a "valid_individual_listing" and flowed into
        # candidates/deduped. It must not, regardless of Tavily's
        # include_domains enforcement.
        results = [_result("https://www.ebay.com.au/itm/genuine-listing/123456789")]
        seen = set()
        entry, unique_results = _process_query_results("query", ["trademe.co.nz"], results, seen)

        self.assertEqual(entry["raw_results"], 1)
        self.assertEqual(entry["rejected_ebay"], 1)
        self.assertEqual(entry["valid_individual_listings"], 0)
        self.assertEqual(entry["unique_results"], 0)
        self.assertEqual(unique_results, [])  # never reaches deduped/candidates

    def test_ebay_result_does_not_block_a_later_duplicate_check(self):
        # An eBay URL must not get added to seen_canonical -- it was
        # rejected outright, not "seen" as a legitimate result -- so it
        # must not suppress a later, different result.
        seen = set()
        _process_query_results(
            "q1", [], [_result("https://www.ebay.com.au/itm/genuine-listing/123456789")], seen
        )
        entry2, unique_results2 = _process_query_results(
            "q2", [], [_result("https://www.trademe.co.nz/a/marketplace/listing/999")], seen
        )
        self.assertEqual(entry2["unique_results"], 1)
        self.assertEqual(entry2["valid_individual_listings"], 1)
        self.assertEqual(len(unique_results2), 1)


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
            mock.patch(
                "scanner.discover.write_discovery_report",
                return_value=("reports/discovery_test.json", {}),
            ),
            mock.patch("scanner.discover.update_discovery_index"),
            mock.patch("scanner.discover.WebSearchSource"),
        ]
        self.mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.mock_write_discovery_report = self.mocks[4]
        self.mock_update_discovery_index = self.mocks[5]
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


class TestRunDiscoveryRejectsEbayResults(_RunDiscoveryTestBase):
    """End-to-end regression test (PR #5 review): an eBay listing returned
    by the search provider -- however it got past include_domains -- must
    never become an opportunity. If this weren't fixed, the eBay result
    would pass is_individual_listing_url(), become the sole candidate, and
    flow into the per-candidate valuation loop below."""

    def test_ebay_result_never_becomes_an_opportunity(self):
        self.mock_source.search.return_value = [
            _result("https://www.ebay.com.au/itm/genuine-listing/123456789"),
        ]

        opportunities = run_discovery(self._config())

        self.assertEqual(opportunities, [])


class TestRunDiscoveryVerificationGate(_RunDiscoveryTestBase):
    """Phase 4B.1: a candidate must never reach product ID / comparable
    research / valuation / scoring unless listing_verification.verify_listing()
    reports it as "verified". These tests mock verify_listing itself (its own
    per-source behaviour is covered by tests/test_listing_verification.py) and
    check the gate in run_discovery() actually enforces the drop."""

    def setUp(self):
        super().setUp()
        self.mock_source.search.return_value = [
            _result("https://www.turners.co.nz/General-Goods/Search/electronics/cameras--equipment/28374370/"),
        ]

    def test_unverified_candidate_never_reaches_identify_product(self):
        with mock.patch("scanner.discover.verify_listing") as mock_verify:
            with mock.patch("scanner.discover.identify_product") as mock_identify:
                with mock.patch("scanner.discover.research_comparables") as mock_research:
                    mock_verify.return_value = mock.Mock(status="unavailable", price=None, reason="no price")
                    opportunities = run_discovery(self._config())

        self.assertEqual(opportunities, [])
        mock_identify.assert_not_called()
        mock_research.assert_not_called()

    def test_unsupported_candidate_never_reaches_identify_product(self):
        with mock.patch("scanner.discover.verify_listing") as mock_verify:
            with mock.patch("scanner.discover.identify_product") as mock_identify:
                mock_verify.return_value = mock.Mock(status="unsupported", price=None, reason="robots.txt disallows")
                opportunities = run_discovery(self._config())

        self.assertEqual(opportunities, [])
        mock_identify.assert_not_called()

    def test_verified_candidate_reaches_identify_product_with_authoritative_price(self):
        from scanner.models import ProductIdentification, ResaleValuation

        with mock.patch("scanner.discover.verify_listing") as mock_verify:
            with mock.patch("scanner.discover.identify_product") as mock_identify:
                with mock.patch("scanner.discover.research_comparables", return_value=[]):
                    with mock.patch("scanner.discover.research", return_value={}):
                        with mock.patch("scanner.discover.trader_review") as mock_trader:
                            mock_verify.return_value = mock.Mock(
                                status="verified", price=199.0, is_live=True, reason=""
                            )
                            mock_identify.return_value = ProductIdentification()
                            mock_trader.return_value = (ResaleValuation(), {"ran": False})
                            opportunities = run_discovery(self._config())

        mock_identify.assert_called_once()
        self.assertEqual(len(opportunities), 1)
        # The snippet-derived price (None, from _result()'s default) must
        # have been overwritten with the verified, authoritative price
        # before identify_product/valuation ran on the candidate.
        self.assertEqual(opportunities[0].current_price, 199.0)

    def test_verification_dropped_count_is_logged(self):
        import io
        import contextlib

        with mock.patch("scanner.discover.verify_listing") as mock_verify:
            with mock.patch("scanner.discover.identify_product"):
                mock_verify.return_value = mock.Mock(status="unavailable", price=None, reason="no price")
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    run_discovery(self._config())

        output = buf.getvalue()
        self.assertIn("verification:", output)
        self.assertIn("1 dropped", output)


class TestRunDiscoveryPersistsReport(_RunDiscoveryTestBase):
    """Phase 4B.2: every run_discovery() call must persist its results via
    write_discovery_report()/update_discovery_index(), even when zero
    opportunities are found -- the run itself (queries/candidates/
    verification counts) is still worth recording for debugging."""

    def test_empty_run_still_persists_a_report(self):
        run_discovery(self._config())

        self.mock_write_discovery_report.assert_called_once()
        opportunities_arg, run_meta_arg = self.mock_write_discovery_report.call_args[0]
        self.assertEqual(opportunities_arg, [])
        self.assertEqual(run_meta_arg["opportunity_count"], 0)
        self.assertEqual(run_meta_arg["decision_counts"], {})
        self.assertEqual(run_meta_arg["mode"], "discover")
        self.mock_update_discovery_index.assert_called_once()
        # update_discovery_index must be called with exactly what
        # write_discovery_report returned, not recomputed.
        index_args = self.mock_update_discovery_index.call_args[0]
        self.assertEqual(index_args, ("reports/discovery_test.json", {}))

    def test_run_meta_reflects_verification_counts_and_decisions(self):
        from scanner.models import ProductIdentification, ResaleValuation

        self.mock_source.search.return_value = [
            _result("https://www.turners.co.nz/General-Goods/Search/electronics/cameras--equipment/1/"),
            _result("https://www.turners.co.nz/General-Goods/Search/electronics/cameras--equipment/2/"),
        ]
        with mock.patch("scanner.discover.verify_listing") as mock_verify:
            mock_verify.side_effect = [
                mock.Mock(status="verified", price=100.0, reason=""),
                mock.Mock(status="unavailable", price=None, reason="no price"),
            ]
            with mock.patch("scanner.discover.identify_product", return_value=ProductIdentification()):
                with mock.patch("scanner.discover.research_comparables", return_value=[]):
                    with mock.patch("scanner.discover.research", return_value={}):
                        with mock.patch(
                            "scanner.discover.trader_review",
                            return_value=(ResaleValuation(), {"ran": False}),
                        ):
                            opportunities = run_discovery(self._config())

        # No quick_sale_low on the fallback ResaleValuation() -> decide()
        # returns PASS ("Missing price or valuation data") for the one
        # candidate that survived verification.
        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0].decision, "PASS")

        _, run_meta_arg = self.mock_write_discovery_report.call_args[0]
        self.assertEqual(run_meta_arg["candidates_found"], 2)
        self.assertEqual(run_meta_arg["candidates_verified"], 1)
        self.assertEqual(run_meta_arg["candidates_verification_dropped"], 1)
        self.assertEqual(run_meta_arg["opportunity_count"], 1)
        self.assertEqual(run_meta_arg["decision_counts"], {"PASS": 1})


if __name__ == "__main__":
    unittest.main()
