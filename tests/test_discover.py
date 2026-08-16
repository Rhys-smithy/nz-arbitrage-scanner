import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from unittest import mock

from scanner.discover import (
    DEFAULT_DISCOVERY_DOMAINS,
    _acquisition_evidence_tier,
    _candidate_group,
    _process_query_results,
    _select_research_candidates,
    run_discovery,
)
from scanner.search.base import SearchResult
from scanner.models import ProductIdentification, ResaleValuation


def _result(url, title="Item", price=None):
    return SearchResult(title=title, url=url, price=price, currency="NZD", source="web_search:tavily")


def _auction_result(
    url,
    title="Item",
    price=None,
    price_type=None,
    buy_now_price=None,
    reserve_status=None,
):
    """Same idea as _result() but for Turners candidates carrying the
    Phase 4B follow-up auction-state fields (price_type/buy_now_price/
    reserve_status) that _select_research_candidates() and
    valuation.compute_profit_and_roi() now read."""
    return SearchResult(
        title=title,
        url=url,
        price=price,
        currency="NZD",
        source="Turners",
        price_type=price_type,
        buy_now_price=buy_now_price,
        reserve_status=reserve_status,
    )


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


class TestAcquisitionEvidenceTier(unittest.TestCase):
    """Phase 4B follow-up (Run #35 live validation): lower tier = stronger
    evidence that `price` reflects something close to a realistic
    acquisition price. Every case here is driven only by already-scraped
    fields -- no estimated/invented data anywhere in this function."""

    def test_no_price_is_worst_tier(self):
        r = _auction_result("https://www.turners.co.nz/x/1", price=None)
        self.assertEqual(_acquisition_evidence_tier(r), 4)

    def test_buy_now_is_best_tier_regardless_of_other_fields(self):
        r = _auction_result(
            "https://www.turners.co.nz/x/1", price=17400.0, buy_now_price=17400.0, price_type=None
        )
        self.assertEqual(_acquisition_evidence_tier(r), 0)

    def test_current_bid_with_reserve_met_is_tier_one(self):
        r = _auction_result(
            "https://www.turners.co.nz/x/1", price=120.0, price_type="current_bid",
            reserve_status="Reserve Met",
        )
        self.assertEqual(_acquisition_evidence_tier(r), 1)

    def test_current_bid_without_confirmed_reserve_is_tier_two(self):
        # Covers both "reserve_status is None" (e.g. every Turners Vehicle
        # candidate -- that division never scrapes reserve_status) and
        # "Reserve Not Met" -- neither confirms the reserve is cleared, but
        # real bidding has still happened, which is still more informative
        # than an untouched $1 listing.
        r1 = _auction_result("https://www.turners.co.nz/x/1", price=5500.0, price_type="current_bid")
        r2 = _auction_result(
            "https://www.turners.co.nz/x/2", price=50.0, price_type="current_bid",
            reserve_status="Reserve Not Met",
        )
        self.assertEqual(_acquisition_evidence_tier(r1), 2)
        self.assertEqual(_acquisition_evidence_tier(r2), 2)

    def test_starting_bid_is_tier_three(self):
        r = _auction_result(
            "https://www.turners.co.nz/x/1", price=1.0, price_type="starting_bid",
            reserve_status="No Reserve",
        )
        self.assertEqual(_acquisition_evidence_tier(r), 3)

    def test_unknown_auction_state_is_also_tier_three_not_excluded(self):
        # A priced Tavily result (price_type always None for non-Turners
        # sources) must not be excluded outright -- it just ranks alongside
        # starting-bid candidates rather than being treated as evidenced.
        r = _result("https://www.trademe.co.nz/a/marketplace/listing/1", price=250.0)
        self.assertEqual(_acquisition_evidence_tier(r), 3)


class TestCandidateGroup(unittest.TestCase):
    """Phase 4B follow-up: classifies a candidate for FAIR SLOT ALLOCATION
    only (see _select_research_candidates), not for verification."""

    def test_general_goods_url_groups_as_general_goods(self):
        r = _auction_result(
            "https://www.turners.co.nz/General-Goods/Search/electronics/cameras--equipment/28374370/"
        )
        self.assertEqual(_candidate_group(r), "turners_general_goods")

    def test_vehicle_division_url_groups_as_vehicles(self):
        for url in [
            "https://www.turners.co.nz/Cars/Used-Cars-for-Sale/123456/",
            "https://www.turners.co.nz/Trucks-Machinery/Used-Trucks-and-Machinery-for-Sale/654321/",
            "https://www.turners.co.nz/motorcycles-scooters/Used-Motorbikes-for-Sale/111222/",
            "https://www.turners.co.nz/buses-caravans/Used-Caravans-and-Motorhomes-for-Sale/333444/",
        ]:
            with self.subTest(url=url):
                self.assertEqual(_candidate_group(_auction_result(url)), "turners_vehicles")

    def test_non_turners_url_groups_as_other(self):
        r = _result("https://www.trademe.co.nz/a/marketplace/listing/999")
        self.assertEqual(_candidate_group(r), "other")


class TestSelectResearchCandidates(unittest.TestCase):
    """Phase 4B follow-up: the round-robin/evidence-tier replacement for the
    old global cheapest-first sort+slice. See _select_research_candidates()
    docstring in scanner/discover.py for the full rationale."""

    def _gg(self, n, price=1.0, price_type="starting_bid", reserve_status=None):
        return [
            _auction_result(
                f"https://www.turners.co.nz/General-Goods/Search/electronics/cameras/{i}/",
                title=f"GG item {i}", price=price, price_type=price_type, reserve_status=reserve_status,
            )
            for i in range(n)
        ]

    def _vehicles(self, n, price=1.0, price_type="current_bid"):
        return [
            _auction_result(
                f"https://www.turners.co.nz/Cars/Used-Cars-for-Sale/{200000 + i}/",
                title=f"Vehicle {i}", price=price, price_type=price_type,
            )
            for i in range(n)
        ]

    def test_general_goods_cannot_completely_starve_vehicles(self):
        # This is exactly Run #35's observed failure mode: a large pool of
        # $1 starting-bid General Goods candidates (131 raw that run) vs a
        # much smaller Vehicles pool (80 raw that run) -- General Goods
        # must no longer be able to take every one of max_research_items'
        # slots purely by outnumbering Vehicles and sorting first.
        candidates = self._gg(40) + self._vehicles(3)  # GG appended first, same as config order
        selected = _select_research_candidates(candidates, max_research=5, prefer_below=250)

        groups = {_candidate_group(r) for r in selected}
        self.assertIn("turners_vehicles", groups)
        vehicle_count = sum(1 for r in selected if _candidate_group(r) == "turners_vehicles")
        self.assertGreaterEqual(vehicle_count, 1)

    def test_evidence_tier_beats_cheaper_but_unevidenced_candidate_within_a_group(self):
        cheap_starting_bid = _auction_result(
            "https://www.turners.co.nz/General-Goods/Search/electronics/x/1/",
            title="Cheap unevidenced", price=1.0, price_type="starting_bid",
        )
        pricier_real_bid = _auction_result(
            "https://www.turners.co.nz/General-Goods/Search/electronics/x/2/",
            title="Real bidding", price=120.0, price_type="current_bid", reserve_status="Reserve Met",
        )
        selected = _select_research_candidates(
            [cheap_starting_bid, pricier_real_bid], max_research=1, prefer_below=250
        )

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].title, "Real bidding")

    def test_prefer_purchase_price_below_still_breaks_ties_within_a_tier(self):
        over_budget = _auction_result(
            "https://www.turners.co.nz/General-Goods/Search/electronics/x/1/",
            title="Over budget", price=400.0, price_type="current_bid", reserve_status="Reserve Met",
        )
        within_budget = _auction_result(
            "https://www.turners.co.nz/General-Goods/Search/electronics/x/2/",
            title="Within budget", price=200.0, price_type="current_bid", reserve_status="Reserve Met",
        )
        selected = _select_research_candidates(
            [over_budget, within_budget], max_research=1, prefer_below=250
        )

        self.assertEqual(selected[0].title, "Within budget")

    def test_does_not_exceed_max_research_items(self):
        candidates = self._gg(10) + self._vehicles(10)
        selected = _select_research_candidates(candidates, max_research=5, prefer_below=250)
        self.assertEqual(len(selected), 5)

    def test_deterministic_across_repeated_calls(self):
        candidates = self._gg(12) + self._vehicles(5)
        first = _select_research_candidates(candidates, max_research=5, prefer_below=250)
        second = _select_research_candidates(candidates, max_research=5, prefer_below=250)
        self.assertEqual([r.url for r in first], [r.url for r in second])

    def test_fewer_candidates_than_budget_returns_all_of_them(self):
        candidates = self._gg(2) + self._vehicles(1)
        selected = _select_research_candidates(candidates, max_research=5, prefer_below=250)
        self.assertEqual(len(selected), 3)


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
            mock.patch("scanner.discover.AuctionSearchSource"),
        ]
        self.mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.mock_source_cls = self.mocks[4]
        self.mock_source = self.mock_source_cls.return_value
        self.mock_source.available = True
        self.mock_source.search.return_value = []  # no results -> no candidates reach valuation

        self.mock_auction_source_cls = self.mocks[5]
        self.mock_auction_source = self.mock_auction_source_cls.return_value
        self.mock_auction_source.search.return_value = []  # no Turners results by default


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


class TestRunDiscoveryAuctionSourceWiring(_RunDiscoveryTestBase):
    """Phase: connect the existing (previously unused) AuctionSearchSource
    to discover.py. It must be built from the same config dict passed into
    run_discovery(), and called once per run with no query argument (it is
    config-driven -- categories/sites come from config, not from a query
    string, unlike Tavily)."""

    def test_auction_search_source_constructed_from_run_config(self):
        cfg = self._config()
        run_discovery(cfg)
        self.mock_auction_source_cls.assert_called_once_with(cfg)

    def test_auction_source_search_called_with_no_query_args(self):
        run_discovery(self._config())
        self.mock_auction_source.search.assert_called_once_with()

    def test_auction_source_called_before_the_first_tavily_query(self):
        call_order = []
        self.mock_auction_source.search.side_effect = lambda *a, **k: call_order.append("auction") or []
        self.mock_source.search.side_effect = lambda *a, **k: call_order.append("tavily") or []

        run_discovery(self._config(products=["Nintendo Switch"], max_queries=2))

        self.assertGreater(len(call_order), 0)
        self.assertEqual(call_order[0], "auction")
        self.assertIn("tavily", call_order)


class TestRunDiscoveryAuctionSourceCandidates(_RunDiscoveryTestBase):
    """Turners candidates sourced via AuctionSearchSource must flow through
    exactly the same is_individual_listing_url() -> cap -> verify_listing()
    -> identify_product()/research_comparables()/valuation/scoring pipeline
    as Tavily results -- no special-casing downstream of candidate sourcing."""

    TURNERS_URL = "https://www.turners.co.nz/General-Goods/Search/electronics/cameras--equipment/28374370/"

    def setUp(self):
        super().setUp()
        self.mock_auction_source.search.return_value = [
            _result(self.TURNERS_URL, title="Canon EOS 200D DSLR", price=120.0),
        ]

    def _run_with_mocked_pipeline(self, verify_status="verified", verify_price=120.0):
        with mock.patch("scanner.discover.verify_listing") as mock_verify:
            with mock.patch("scanner.discover.identify_product") as mock_identify:
                with mock.patch("scanner.discover.research_comparables", return_value=[]):
                    with mock.patch("scanner.discover.research", return_value={}):
                        with mock.patch("scanner.discover.trader_review") as mock_trader:
                            mock_verify.return_value = mock.Mock(
                                status=verify_status, price=verify_price, is_live=True, reason=""
                            )
                            mock_identify.return_value = ProductIdentification()
                            mock_trader.return_value = (ResaleValuation(), {"ran": False})
                            opportunities = run_discovery(self._config())
        return opportunities, mock_identify

    def test_turners_candidate_enters_discovery_and_becomes_an_opportunity(self):
        opportunities, mock_identify = self._run_with_mocked_pipeline()

        mock_identify.assert_called_once()
        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0].url, self.TURNERS_URL)
        self.assertEqual(opportunities[0].source, "Turners")
        # Verification overwrites the price with the authoritative one, same
        # as it does for every other source.
        self.assertEqual(opportunities[0].current_price, 120.0)

    def test_turners_candidate_still_subject_to_the_verification_gate(self):
        opportunities, mock_identify = self._run_with_mocked_pipeline(
            verify_status="unavailable", verify_price=None
        )

        self.assertEqual(opportunities, [])
        mock_identify.assert_not_called()

    def test_non_listing_turners_url_never_becomes_a_candidate(self):
        # A Turners category/search page (no trailing item id) must be
        # rejected the same way it would be for a Tavily result -- Turners
        # sourcing does not bypass is_individual_listing_url().
        self.mock_auction_source.search.return_value = [
            _result("https://www.turners.co.nz/General-Goods/Search/electronics/", title="Category page"),
        ]
        with mock.patch("scanner.discover.identify_product") as mock_identify:
            opportunities = run_discovery(self._config())

        self.assertEqual(opportunities, [])
        mock_identify.assert_not_called()


class TestRunDiscoveryVehiclesNotStarvedByGeneralGoods(_RunDiscoveryTestBase):
    """End-to-end regression test for Run #35's observed failure mode: a
    large pool of $1 starting-bid General Goods candidates must not be able
    to consume every max_research_items slot and lock Vehicles out
    entirely, purely because General Goods is scraped first and both sides
    tie on price."""

    def setUp(self):
        super().setUp()
        gg_candidates = [
            _auction_result(
                f"https://www.turners.co.nz/General-Goods/Search/electronics/cameras/{i}/",
                title=f"GG item {i}", price=1.0, price_type="starting_bid",
            )
            for i in range(40)  # far more than max_research_items=5
        ]
        vehicle_candidates = [
            _auction_result(
                f"https://www.turners.co.nz/Cars/Used-Cars-for-Sale/{200000 + i}/",
                title=f"Vehicle {i}", price=1.0, price_type="current_bid",
            )
            for i in range(3)
        ]
        # General Goods listed first, exactly mirroring config.json's
        # turners_categories order (General Goods categories before Cars/
        # Trucks & Machinery/Motorbikes/Trailers & Caravans) and
        # AuctionSearchSource.search()'s iteration order.
        self.mock_auction_source.search.return_value = gg_candidates + vehicle_candidates

    def test_at_least_one_vehicle_candidate_reaches_identify_product(self):
        with mock.patch("scanner.discover.verify_listing") as mock_verify:
            with mock.patch("scanner.discover.identify_product") as mock_identify:
                with mock.patch("scanner.discover.research_comparables", return_value=[]):
                    with mock.patch("scanner.discover.research", return_value={}):
                        with mock.patch("scanner.discover.trader_review") as mock_trader:
                            mock_verify.side_effect = lambda url, cache: mock.Mock(
                                status="verified", price=1.0, is_live=True, reason=""
                            )
                            mock_identify.return_value = ProductIdentification()
                            mock_trader.return_value = (ResaleValuation(), {"ran": False})
                            run_discovery(self._config())

        identified_titles = {call.args[0] for call in mock_identify.call_args_list}
        vehicle_titles = {t for t in identified_titles if t.startswith("Vehicle")}
        self.assertGreaterEqual(
            len(vehicle_titles), 1,
            f"expected at least one Vehicle candidate among identified titles, got: {identified_titles}",
        )


class TestRunDiscoveryStartingBidValuationSemantics(_RunDiscoveryTestBase):
    """Phase 4B follow-up regression tests: a `starting_bid` price must not
    be represented as though it were a confirmed acquisition price for
    profit/ROI purposes, while the observed bid itself, cost modelling, and
    max_buy_price (all price-agnostic or explicitly-labelled-as-observed)
    remain exactly as before."""

    TURNERS_URL = "https://www.turners.co.nz/General-Goods/Search/electronics/cameras--equipment/28374370/"

    def _run(self, price_type, verify_price=1.0):
        self.mock_auction_source.search.return_value = [
            _auction_result(self.TURNERS_URL, title="Canon Powershot", price=1.0, price_type=price_type),
        ]
        with mock.patch("scanner.discover.verify_listing") as mock_verify:
            with mock.patch("scanner.discover.identify_product") as mock_identify:
                with mock.patch("scanner.discover.research_comparables", return_value=[]):
                    with mock.patch("scanner.discover.research", return_value={}):
                        with mock.patch("scanner.discover.trader_review") as mock_trader:
                            mock_verify.return_value = mock.Mock(
                                status="verified", price=verify_price, is_live=True, reason=""
                            )
                            mock_identify.return_value = ProductIdentification()
                            # A real ResaleValuation with quick_sale set, so
                            # the real (unmocked) apply_valuation() /
                            # compute_profit_and_roi() actually run --
                            # unlike most other tests in this file, this one
                            # needs to exercise that real arithmetic.
                            mock_trader.return_value = (
                                ResaleValuation(quick_sale_low=400.0, quick_sale_high=550.0, confidence_pct=4.0),
                                {"ran": True},
                            )
                            opportunities = run_discovery(self._config())
        self.assertEqual(len(opportunities), 1)
        return opportunities[0]

    def test_starting_bid_does_not_produce_expected_profit_or_roi(self):
        opp = self._run(price_type="starting_bid")

        self.assertEqual(opp.price_type, "starting_bid")
        # The observed bid is preserved as observed data -- not hidden, not
        # replaced with an estimate.
        self.assertEqual(opp.current_price, 1.0)
        # But it must not be represented as a confirmed acquisition price
        # for profit/ROI purposes.
        self.assertIsNone(opp.expected_net_profit_low)
        self.assertIsNone(opp.expected_net_profit_high)
        self.assertIsNone(opp.roi_low_pct)
        self.assertIsNone(opp.roi_high_pct)

    def test_starting_bid_max_buy_price_is_still_computed(self):
        # max_buy_price is price-agnostic (depends on quick_sale_value and
        # cost_model, not on current_price/price_type) -- it is the
        # legitimate, actionable ceiling regardless of auction stage, and
        # must not be suppressed by this fix.
        opp = self._run(price_type="starting_bid")
        self.assertIsNotNone(opp.max_buy_price)
        self.assertGreater(opp.max_buy_price, 0)

    def test_current_bid_with_same_price_still_produces_profit_and_roi(self):
        # Proves the fix is scoped to price_type == "starting_bid" only --
        # a real current_bid at the same $1 price is unaffected.
        opp = self._run(price_type="current_bid")

        self.assertEqual(opp.price_type, "current_bid")
        self.assertIsNotNone(opp.expected_net_profit_low)
        self.assertIsNotNone(opp.roi_low_pct)

    def test_unknown_price_type_non_turners_behaviour_unchanged(self):
        # price_type is None for every existing (pre-Phase-4B) source --
        # Tavily/SerpAPI/Brave never set it. Profit/ROI computation for
        # those candidates must be completely unaffected by this change.
        opp = self._run(price_type=None)

        self.assertIsNone(opp.price_type)
        self.assertIsNotNone(opp.expected_net_profit_low)
        self.assertIsNotNone(opp.roi_low_pct)


class TestRunDiscoveryAuctionWinsCanonicalDuplicate(_RunDiscoveryTestBase):
    """Turners is processed before Tavily specifically so that when the same
    listing is found by both, the Turners copy (real scraped price) wins the
    canonical-URL duplicate check and Tavily's copy (snippet-only, often no
    price) is dropped."""

    TURNERS_URL = "https://www.turners.co.nz/General-Goods/Search/electronics/cameras--equipment/28374370/"

    def setUp(self):
        super().setUp()
        self.mock_auction_source.search.return_value = [
            _result(self.TURNERS_URL, title="Turners: Canon EOS 200D", price=120.0),
        ]
        # Same listing, different query string -- canonicalize_url() strips
        # tracking params, so this must still collapse to the same key.
        self.mock_source.search.return_value = [
            _result(
                self.TURNERS_URL + "?utm_source=newsletter",
                title="Tavily snippet: Canon camera",
                price=None,
            ),
        ]

    def test_process_query_results_logs_the_tavily_copy_as_a_duplicate(self):
        seen: set = set()
        _process_query_results(
            "auction_source:turners", ["turners.co.nz"],
            self.mock_auction_source.search.return_value, seen,
        )
        tavily_entry, tavily_unique = _process_query_results(
            "some tavily query", ["turners.co.nz"],
            self.mock_source.search.return_value, seen,
        )
        self.assertEqual(tavily_entry["rejected_duplicate"], 1)
        self.assertEqual(tavily_unique, [])

    def test_only_one_opportunity_survives_and_it_is_the_turners_copy(self):
        with mock.patch("scanner.discover.verify_listing") as mock_verify:
            with mock.patch("scanner.discover.identify_product") as mock_identify:
                with mock.patch("scanner.discover.research_comparables", return_value=[]):
                    with mock.patch("scanner.discover.research", return_value={}):
                        with mock.patch("scanner.discover.trader_review") as mock_trader:
                            mock_verify.return_value = mock.Mock(
                                status="verified", price=120.0, is_live=True, reason=""
                            )
                            mock_identify.return_value = ProductIdentification()
                            mock_trader.return_value = (ResaleValuation(), {"ran": False})
                            opportunities = run_discovery(self._config())

        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0].title, "Turners: Canon EOS 200D")
        mock_identify.assert_called_once()


class TestRunDiscoveryExistingTavilyBehaviourIntact(_RunDiscoveryTestBase):
    """Adding the auction source must not change Tavily's own call shape or
    the include_domains behaviour already covered above -- these are a
    couple of extra direct checks against interference between the two
    sources sharing one run."""

    def test_tavily_still_receives_include_domains_with_auction_source_wired_in(self):
        run_discovery(self._config())
        self.assertTrue(self.mock_source.search.called)
        for call in self.mock_source.search.call_args_list:
            self.assertEqual(call.kwargs.get("include_domains"), DEFAULT_DISCOVERY_DOMAINS)

    def test_auction_source_results_do_not_leak_into_tavily_call_kwargs(self):
        # Deliberately a category page, not an individual listing -- it must
        # never reach candidates/verify_listing (a real network call), since
        # this test only cares about what discover.py passes to Tavily.
        self.mock_auction_source.search.return_value = [
            _result("https://www.turners.co.nz/General-Goods/Search/electronics/"),
        ]
        run_discovery(self._config())
        for call in self.mock_source.search.call_args_list:
            self.assertNotIn("turners_categories", call.kwargs)

    def test_tavily_still_runs_when_auction_source_raises_unexpectedly(self):
        # AuctionSearchSource itself already swallows its own scraper-level
        # failures (see tests/test_auction_search.py) -- this covers the
        # last-resort guard in run_discovery() for a genuinely unexpected
        # failure (e.g. a bug in the class itself), confirming it can never
        # take down the Tavily loop in the same run.
        self.mock_auction_source.search.side_effect = RuntimeError("unexpected")
        result = run_discovery(self._config())

        self.assertEqual(result, [])
        self.assertTrue(self.mock_source.search.called)


class TestRunDiscoveryTavilyUnavailable(_RunDiscoveryTestBase):
    """Regression: an unavailable WebSearchSource must not exit
    run_discovery() early. Turners direct-scrape discovery
    (AuctionSearchSource) has its own working scrapers and does not depend
    on a Tavily/web-search API key at all -- the old `return []` right
    after the availability check predates AuctionSearchSource being wired
    into this function and was only ever correct when Tavily was the sole
    candidate source discover.py had."""

    TURNERS_URL = "https://www.turners.co.nz/General-Goods/Search/electronics/cameras--equipment/28374370/"

    def setUp(self):
        super().setUp()
        self.mock_source.available = False  # simulate no WEB_SEARCH_PROVIDER/API key configured
        self.mock_auction_source.search.return_value = [
            _result(self.TURNERS_URL, title="Canon EOS 200D DSLR", price=120.0),
        ]

    def test_does_not_return_early_when_web_search_unavailable(self):
        # Direct regression guard: if the old hard `return []` were ever
        # reintroduced, AuctionSearchSource would never be constructed and
        # this assertion would fail. verify_listing is mocked purely so the
        # Turners candidate doesn't reach a real network call -- this test
        # only cares that AuctionSearchSource was constructed and searched.
        with mock.patch("scanner.discover.verify_listing") as mock_verify:
            mock_verify.return_value = mock.Mock(status="unavailable", price=None, reason="test-mocked")
            run_discovery(self._config())
        self.mock_auction_source_cls.assert_called_once()

    def test_auction_source_still_runs_and_tavily_query_loop_is_skipped(self):
        with mock.patch("scanner.discover.verify_listing") as mock_verify:
            mock_verify.return_value = mock.Mock(status="unavailable", price=None, reason="test-mocked")
            run_discovery(self._config())

        self.mock_auction_source.search.assert_called_once_with()
        # No queries were generated (no Tavily provider to query) -- Tavily's
        # search() must never be called in this run.
        self.mock_source.search.assert_not_called()

    def test_turners_candidate_reaches_verification_and_becomes_an_opportunity(self):
        with mock.patch("scanner.discover.verify_listing") as mock_verify:
            with mock.patch("scanner.discover.identify_product") as mock_identify:
                with mock.patch("scanner.discover.research_comparables", return_value=[]):
                    with mock.patch("scanner.discover.research", return_value={}):
                        with mock.patch("scanner.discover.trader_review") as mock_trader:
                            mock_verify.return_value = mock.Mock(
                                status="verified", price=120.0, is_live=True, reason=""
                            )
                            mock_identify.return_value = ProductIdentification()
                            mock_trader.return_value = (ResaleValuation(), {"ran": False})
                            opportunities = run_discovery(self._config())

        mock_verify.assert_called_once_with(self.TURNERS_URL, mock.ANY)
        mock_identify.assert_called_once()
        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0].url, self.TURNERS_URL)
        self.assertEqual(opportunities[0].source, "Turners")
        self.assertEqual(opportunities[0].current_price, 120.0)

    def test_turners_candidate_still_gated_by_verification_when_tavily_unavailable(self):
        # The verification gate (Phase 4B.1) must keep applying to Turners
        # candidates regardless of why Tavily wasn't queried this run.
        with mock.patch("scanner.discover.verify_listing") as mock_verify:
            with mock.patch("scanner.discover.identify_product") as mock_identify:
                mock_verify.return_value = mock.Mock(status="unavailable", price=None, reason="no price")
                opportunities = run_discovery(self._config())

        self.assertEqual(opportunities, [])
        mock_identify.assert_not_called()

    def test_returns_empty_list_not_none_when_both_sources_have_nothing(self):
        self.mock_auction_source.search.return_value = []
        result = run_discovery(self._config())
        self.assertEqual(result, [])


class TestRunDiscoveryTavilyAvailablePathUnchanged(_RunDiscoveryTestBase):
    """Companion to TestRunDiscoveryTavilyUnavailable above: when a web
    search provider IS configured, the query-generation/search path must be
    byte-for-byte what it was before Turners direct-scrape discovery was
    wired in -- decoupling the unavailable case must not touch this branch."""

    def test_queries_are_generated_and_tavily_is_searched_when_available(self):
        # self.mock_source.available stays True (the _RunDiscoveryTestBase
        # default) -- this is the existing Tavily-enabled behaviour.
        run_discovery(self._config(max_queries=3, products=["Nintendo Switch"]))

        self.assertTrue(self.mock_source.search.called)
        for call in self.mock_source.search.call_args_list:
            self.assertEqual(call.kwargs.get("include_domains"), DEFAULT_DISCOVERY_DOMAINS)


if __name__ == "__main__":
    unittest.main()
