import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from unittest import mock

from scanner.search.auction_search import AuctionSearchSource
from scanner.search.util import is_individual_listing_url


def _config(turners_categories=None, sites=None):
    return {
        "user_agent": "NZ-Reseller-Scanner/1.0 (test)",
        "request_delay_seconds": 0,
        "turners_categories": turners_categories or [],
        "sites": sites or {},
    }


def _general_goods_item(**overrides):
    item = {
        "source": "Turners",
        "title": "Canon EOS 200D DSLR Camera",
        "url": "https://www.turners.co.nz/General-Goods/Search/electronics/cameras--equipment/28374370/",
        "item_id": "28374370",
        "price": 120.0,
        "price_type": "current_bid",
        "buy_now_price": None,
        "reserve_status": "Reserve Met",
        "closing_date": "12 Aug 26",
        "location": "Auckland",
        "subcategory": "Electronics > Cameras & Equipment",
        "pricing_status": "priced",
        "starts_on": "",
    }
    item.update(overrides)
    return item


def _vehicle_item(**overrides):
    item = {
        "source": "Turners",
        "title": "2015 Toyota Corolla GX",
        "url": "https://www.turners.co.nz/Cars/Used-Cars-for-Sale/123456/",
        "item_id": "123456",
        "subcategory": "Cars",
        "reserve_status": "",
        "closing_date": "",
        "price": None,
        "price_type": None,
        "buy_now_price": 17400.0,
        "odometer": "45,000 km",
        "location": "Christchurch",
    }
    item.update(overrides)
    return item


class TestGeneralGoodsMapping(unittest.TestCase):
    """AuctionSearchSource must preserve the existing General Goods mapping
    (this behaviour is not new, but must not regress when Vehicles support
    is added alongside it)."""

    def test_maps_current_bid_item_to_search_result(self):
        with mock.patch(
            "scanner.search.auction_search.turners_catalog.fetch_all_categories",
            return_value=[_general_goods_item()],
        ) as mock_fetch:
            source = AuctionSearchSource(_config(turners_categories=["Electronics & Tech"]))
            results = source.search()

        mock_fetch.assert_called_once_with("Electronics & Tech", "NZ-Reseller-Scanner/1.0 (test)", 0)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r.title, "Canon EOS 200D DSLR Camera")
        self.assertEqual(
            r.url,
            "https://www.turners.co.nz/General-Goods/Search/electronics/cameras--equipment/28374370/",
        )
        self.assertEqual(r.price, 120.0)
        self.assertEqual(r.currency, "NZD")
        self.assertEqual(r.source, "Turners")
        self.assertEqual(r.location, "Auckland")
        self.assertEqual(r.description, "Electronics > Cameras & Equipment")
        self.assertEqual(r.condition, "unknown")
        self.assertFalse(r.is_sold)

    def test_falls_back_to_buy_now_price_when_no_bid_price(self):
        item = _general_goods_item(price=None, price_type=None, buy_now_price=249.0)
        with mock.patch(
            "scanner.search.auction_search.turners_catalog.fetch_all_categories",
            return_value=[item],
        ):
            source = AuctionSearchSource(_config(turners_categories=["Electronics & Tech"]))
            results = source.search()

        self.assertEqual(results[0].price, 249.0)

    def test_representative_general_goods_url_is_a_valid_individual_listing(self):
        with mock.patch(
            "scanner.search.auction_search.turners_catalog.fetch_all_categories",
            return_value=[_general_goods_item()],
        ):
            source = AuctionSearchSource(_config(turners_categories=["Electronics & Tech"]))
            results = source.search()

        self.assertTrue(is_individual_listing_url(results[0].url))


class TestVehiclesMapping(unittest.TestCase):
    """New: AuctionSearchSource previously only supported General Goods --
    Vehicles categories (from turners_vehicles.DIVISIONS) silently produced
    zero results because turners_catalog.CATEGORY_SLUGS has no entry for
    them. This is the fix."""

    def test_maps_buy_now_vehicle_item_to_search_result(self):
        with mock.patch(
            "scanner.search.auction_search.turners_vehicles.fetch_all_divisions",
            return_value=[_vehicle_item()],
        ) as mock_fetch:
            source = AuctionSearchSource(_config(turners_categories=["Cars"]))
            results = source.search()

        mock_fetch.assert_called_once_with(["Cars"], "NZ-Reseller-Scanner/1.0 (test)", 0)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r.title, "2015 Toyota Corolla GX")
        self.assertEqual(r.url, "https://www.turners.co.nz/Cars/Used-Cars-for-Sale/123456/")
        self.assertEqual(r.price, 17400.0)  # falls back to buy_now_price, no bid price present
        self.assertEqual(r.currency, "NZD")
        self.assertEqual(r.source, "Turners")
        self.assertEqual(r.location, "Christchurch")
        self.assertIn("Cars", r.description)
        self.assertIn("45,000 km", r.description)
        self.assertFalse(r.is_sold)

    def test_prefers_bid_price_over_buy_now_when_both_present(self):
        item = _vehicle_item(price=15500.0, price_type="current_bid", buy_now_price=17400.0)
        with mock.patch(
            "scanner.search.auction_search.turners_vehicles.fetch_all_divisions",
            return_value=[item],
        ):
            source = AuctionSearchSource(_config(turners_categories=["Cars"]))
            results = source.search()

        self.assertEqual(results[0].price, 15500.0)

    def test_description_has_no_odometer_suffix_when_odometer_missing(self):
        item = _vehicle_item(odometer="")
        with mock.patch(
            "scanner.search.auction_search.turners_vehicles.fetch_all_divisions",
            return_value=[item],
        ):
            source = AuctionSearchSource(_config(turners_categories=["Cars"]))
            results = source.search()

        self.assertEqual(results[0].description, "Cars")

    def test_representative_vehicle_url_is_a_valid_individual_listing(self):
        with mock.patch(
            "scanner.search.auction_search.turners_vehicles.fetch_all_divisions",
            return_value=[_vehicle_item()],
        ):
            source = AuctionSearchSource(_config(turners_categories=["Cars"]))
            results = source.search()

        self.assertTrue(is_individual_listing_url(results[0].url))

    def test_all_four_vehicle_divisions_route_to_the_vehicles_fetcher(self):
        # Regression guard: every division name in turners_vehicles.DIVISIONS
        # must be routed to fetch_all_divisions, not silently dropped by
        # falling through to the General Goods path (which has no slug for
        # any of them and would return zero results with no visible error).
        from scanner.scrapers.turners_vehicles import DIVISIONS

        for division_name in DIVISIONS:
            with mock.patch(
                "scanner.search.auction_search.turners_vehicles.fetch_all_divisions",
                return_value=[],
            ) as mock_vehicles, mock.patch(
                "scanner.search.auction_search.turners_catalog.fetch_all_categories",
                return_value=[],
            ) as mock_general:
                source = AuctionSearchSource(_config(turners_categories=[division_name]))
                source.search()

            mock_vehicles.assert_called_once()
            mock_general.assert_not_called()


class TestMixedCategories(unittest.TestCase):
    def test_general_goods_and_vehicle_categories_in_the_same_run(self):
        with mock.patch(
            "scanner.search.auction_search.turners_catalog.fetch_all_categories",
            return_value=[_general_goods_item()],
        ) as mock_general, mock.patch(
            "scanner.search.auction_search.turners_vehicles.fetch_all_divisions",
            return_value=[_vehicle_item()],
        ) as mock_vehicles:
            source = AuctionSearchSource(
                _config(turners_categories=["Electronics & Tech", "Cars"])
            )
            results = source.search()

        mock_general.assert_called_once_with("Electronics & Tech", mock.ANY, mock.ANY)
        mock_vehicles.assert_called_once_with(["Cars"], mock.ANY, mock.ANY)
        self.assertEqual(len(results), 2)
        sources_and_urls = {(r.title, r.url) for r in results}
        self.assertIn(("Canon EOS 200D DSLR Camera", _general_goods_item()["url"]), sources_and_urls)
        self.assertIn(("2015 Toyota Corolla GX", _vehicle_item()["url"]), sources_and_urls)


class TestErrorAndEmptyCases(unittest.TestCase):
    def test_empty_turners_categories_returns_empty_list_with_no_fetch_calls(self):
        with mock.patch(
            "scanner.search.auction_search.turners_catalog.fetch_all_categories"
        ) as mock_general, mock.patch(
            "scanner.search.auction_search.turners_vehicles.fetch_all_divisions"
        ) as mock_vehicles:
            source = AuctionSearchSource(_config(turners_categories=[]))
            results = source.search()

        self.assertEqual(results, [])
        mock_general.assert_not_called()
        mock_vehicles.assert_not_called()

    def test_general_goods_fetch_exception_is_swallowed_not_raised(self):
        with mock.patch(
            "scanner.search.auction_search.turners_catalog.fetch_all_categories",
            side_effect=RuntimeError("boom"),
        ):
            source = AuctionSearchSource(_config(turners_categories=["Electronics & Tech"]))
            results = source.search()  # must not raise

        self.assertEqual(results, [])

    def test_vehicles_fetch_exception_is_swallowed_not_raised(self):
        with mock.patch(
            "scanner.search.auction_search.turners_vehicles.fetch_all_divisions",
            side_effect=RuntimeError("boom"),
        ):
            source = AuctionSearchSource(_config(turners_categories=["Cars"]))
            results = source.search()  # must not raise

        self.assertEqual(results, [])

    def test_unrecognised_category_name_falls_through_to_general_goods_path_harmlessly(self):
        # Not a vehicle division -> takes the General Goods path. That
        # function already handles an unmapped category name gracefully
        # (CATEGORY_SLUGS.get(name, []) -> no slugs -> no items), so this
        # must not raise and must not call the vehicles fetcher.
        with mock.patch(
            "scanner.search.auction_search.turners_catalog.fetch_all_categories",
            return_value=[],
        ) as mock_general, mock.patch(
            "scanner.search.auction_search.turners_vehicles.fetch_all_divisions"
        ) as mock_vehicles:
            source = AuctionSearchSource(_config(turners_categories=["Not A Real Category"]))
            results = source.search()

        self.assertEqual(results, [])
        mock_general.assert_called_once()
        mock_vehicles.assert_not_called()

    def test_no_sites_configured_returns_only_turners_results(self):
        with mock.patch(
            "scanner.search.auction_search.turners_catalog.fetch_all_categories",
            return_value=[_general_goods_item()],
        ), mock.patch(
            "scanner.search.auction_search.thorntons.fetch_listings"
        ) as mock_thorntons, mock.patch(
            "scanner.search.auction_search.mainland_auctions.fetch_listings"
        ) as mock_mainland:
            source = AuctionSearchSource(_config(turners_categories=["Electronics & Tech"], sites={}))
            results = source.search()

        self.assertEqual(len(results), 1)
        mock_thorntons.assert_not_called()
        mock_mainland.assert_not_called()


if __name__ == "__main__":
    unittest.main()
