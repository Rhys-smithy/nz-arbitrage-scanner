import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from unittest import mock

import requests

from scanner.listing_verification import VerificationCache, verify_listing

GENERAL_GOODS_URL = "https://www.turners.co.nz/General-Goods/Search/electronics/cameras--equipment/28374370/"
VEHICLE_URL = "https://www.turners.co.nz/Cars/Used-Cars-for-Sale/mitsubishi/outlander/28054725"
TRADEME_URL = "https://www.trademe.co.nz/a/marketplace/listing/12345"
THORNTONS_URL = "https://www.thorntons.net.nz/auctions/detail/456"
MAINLAND_URL = "https://www.mainlandauctions.nz/auctions/some-auction"


def _cache():
    # request_delay=0 so tests don't actually sleep.
    return VerificationCache(user_agent="NZ-Reseller-Scanner/1.0 (test)", request_delay=0)


class TestTurnersGeneralGoods(unittest.TestCase):
    @mock.patch("scanner.listing_verification.fetch_category_items")
    @mock.patch("scanner.listing_verification.fetch_item_detail")
    def test_verified_when_item_found_with_price(self, mock_detail, mock_catalog):
        mock_detail.return_value = {
            "condition": "Very Tidy", "testing_level": "Untested", "quantity": "1",
            "comments": "Canon EOS 80D",
        }
        mock_catalog.return_value = [
            {"item_id": "28374370", "price": 200.0, "buy_now_price": None, "pricing_status": "priced"},
            {"item_id": "99999999", "price": 50.0, "buy_now_price": None, "pricing_status": "priced"},
        ]

        result = verify_listing(GENERAL_GOODS_URL, _cache())

        self.assertEqual(result.status, "verified")
        self.assertEqual(result.price, 200.0)
        self.assertIn("Very Tidy", result.condition_text)
        self.assertTrue(result.is_live)
        mock_catalog.assert_called_once_with("electronics/cameras--equipment", "NZ-Reseller-Scanner/1.0 (test)")

    @mock.patch("scanner.listing_verification.fetch_category_items")
    @mock.patch("scanner.listing_verification.fetch_item_detail")
    def test_unavailable_not_confirmed_dead_when_absent_from_page_one(self, mock_detail, mock_catalog):
        # Item genuinely exists but isn't among the ~20 items fetch_category_items
        # returns for page 1 of its subcategory -- must not be treated as "dead".
        mock_detail.return_value = {"condition": "Tidy", "testing_level": "", "quantity": "", "comments": ""}
        mock_catalog.return_value = [
            {"item_id": "11111111", "price": 10.0, "buy_now_price": None, "pricing_status": "priced"},
        ]

        result = verify_listing(GENERAL_GOODS_URL, _cache())

        self.assertEqual(result.status, "unavailable")
        self.assertIsNone(result.price)
        self.assertIn("not confirmed dead", result.reason)
        # Condition from the detail page is still preserved even though price wasn't verifiable.
        self.assertIn("Tidy", result.condition_text)

    @mock.patch("scanner.listing_verification.fetch_category_items")
    @mock.patch("scanner.listing_verification.fetch_item_detail")
    def test_unavailable_when_pricing_status_not_priced(self, mock_detail, mock_catalog):
        mock_detail.return_value = {"condition": "", "testing_level": "", "quantity": "", "comments": ""}
        mock_catalog.return_value = [
            {"item_id": "28374370", "price": None, "buy_now_price": None, "pricing_status": "no_pricing"},
        ]

        result = verify_listing(GENERAL_GOODS_URL, _cache())

        self.assertEqual(result.status, "unavailable")
        self.assertIsNone(result.price)

    @mock.patch("scanner.listing_verification.fetch_category_items")
    @mock.patch("scanner.listing_verification.fetch_item_detail")
    def test_fetch_failure_degrades_to_unavailable_not_a_crash(self, mock_detail, mock_catalog):
        # fetch_item_detail/fetch_category_items already fail safe on network
        # errors (return their empty defaults) -- verification must not crash
        # or fabricate a price on top of that, just report "unavailable".
        mock_detail.return_value = {"condition": "", "testing_level": "", "quantity": "", "comments": ""}
        mock_catalog.return_value = []

        result = verify_listing(GENERAL_GOODS_URL, _cache())

        self.assertEqual(result.status, "unavailable")
        self.assertIsNone(result.price)

    def test_url_not_matching_item_shape_is_unavailable(self):
        result = verify_listing(
            "https://www.turners.co.nz/General-Goods/Search/electronics/", _cache()
        )
        self.assertEqual(result.status, "unavailable")


def _fake_response(text):
    resp = mock.Mock()
    resp.text = text
    resp.raise_for_status = mock.Mock()
    return resp


class TestTurnersVehicles(unittest.TestCase):
    @mock.patch("scanner.listing_verification.requests.get")
    def test_discounted_buynow_price_verified_from_detail_page(self, mock_get):
        mock_get.return_value = _fake_response(
            "BuyNow Was $18,900 You Save $1,500 $17,400 *All On Road Costs included BuyNow Want Finance?"
        )

        result = verify_listing(VEHICLE_URL, _cache())

        self.assertEqual(result.status, "verified")
        self.assertEqual(result.price, 17400.0)

    @mock.patch("scanner.listing_verification.requests.get")
    def test_non_discounted_buynow_price_verified_from_detail_page(self, mock_get):
        mock_get.return_value = _fake_response(
            "BuyNow $9,500 *All On Road Costs included BuyNow Want Finance?"
        )

        result = verify_listing(VEHICLE_URL, _cache())

        self.assertEqual(result.status, "verified")
        self.assertEqual(result.price, 9500.0)

    @mock.patch("scanner.listing_verification.fetch_division")
    @mock.patch("scanner.listing_verification.requests.get")
    def test_auction_style_vehicle_falls_back_to_division_catalog(self, mock_get, mock_division):
        # Confirmed live during the 4B.1 spike: Starting Bid/Current Bid vehicle
        # detail pages carry no price at all -- must fall back to the catalog.
        mock_get.return_value = _fake_response(
            "Vehicle Type Excavator Odometer 2,651 hr Location Turners Auckland Trucks"
        )
        mock_division.return_value = [
            {"item_id": "28054725", "price": 32100.0, "buy_now_price": None},
        ]

        result = verify_listing(VEHICLE_URL, _cache())

        self.assertEqual(result.status, "verified")
        self.assertEqual(result.price, 32100.0)
        mock_division.assert_called_once_with("Cars", "NZ-Reseller-Scanner/1.0 (test)")

    @mock.patch("scanner.listing_verification.fetch_division")
    @mock.patch("scanner.listing_verification.requests.get")
    def test_tender_style_vehicle_with_no_price_anywhere_is_unavailable(self, mock_get, mock_division):
        mock_get.return_value = _fake_response("Tender Start Date 10 Aug 26 End Date 17 Aug 26 Lot No 010")
        mock_division.return_value = [
            {"item_id": "28054725", "price": None, "buy_now_price": None},
        ]

        result = verify_listing(VEHICLE_URL, _cache())

        self.assertEqual(result.status, "unavailable")
        self.assertIsNone(result.price)

    @mock.patch("scanner.listing_verification.fetch_division")
    @mock.patch("scanner.listing_verification.requests.get")
    def test_detail_fetch_failure_falls_back_to_catalog_not_a_crash(self, mock_get, mock_division):
        mock_get.side_effect = requests.RequestException("boom")
        mock_division.return_value = [
            {"item_id": "28054725", "price": 17400.0, "buy_now_price": None},
        ]

        result = verify_listing(VEHICLE_URL, _cache())

        self.assertEqual(result.status, "verified")
        self.assertEqual(result.price, 17400.0)

    @mock.patch("scanner.listing_verification.fetch_division")
    @mock.patch("scanner.listing_verification.requests.get")
    def test_detail_and_catalog_both_failing_is_unavailable_not_a_crash(self, mock_get, mock_division):
        mock_get.side_effect = requests.RequestException("boom")
        mock_division.return_value = []

        result = verify_listing(VEHICLE_URL, _cache())

        self.assertEqual(result.status, "unavailable")
        self.assertIsNone(result.price)


class TestUnsupportedSourcesMakeNoHttpRequests(unittest.TestCase):
    @mock.patch("scanner.listing_verification.fetch_division")
    @mock.patch("scanner.listing_verification.fetch_category_items")
    @mock.patch("scanner.listing_verification.fetch_item_detail")
    @mock.patch("scanner.listing_verification.requests.get")
    def test_trademe_is_unsupported_and_untouched(self, mock_get, mock_detail, mock_catalog, mock_division):
        result = verify_listing(TRADEME_URL, _cache())

        self.assertEqual(result.status, "unsupported")
        self.assertTrue(result.reason)
        mock_get.assert_not_called()
        mock_detail.assert_not_called()
        mock_catalog.assert_not_called()
        mock_division.assert_not_called()

    @mock.patch("scanner.listing_verification.fetch_division")
    @mock.patch("scanner.listing_verification.fetch_category_items")
    @mock.patch("scanner.listing_verification.fetch_item_detail")
    @mock.patch("scanner.listing_verification.requests.get")
    def test_thorntons_is_unsupported_and_untouched(self, mock_get, mock_detail, mock_catalog, mock_division):
        result = verify_listing(THORNTONS_URL, _cache())

        self.assertEqual(result.status, "unsupported")
        mock_get.assert_not_called()
        mock_detail.assert_not_called()
        mock_catalog.assert_not_called()
        mock_division.assert_not_called()

    @mock.patch("scanner.listing_verification.fetch_division")
    @mock.patch("scanner.listing_verification.fetch_category_items")
    @mock.patch("scanner.listing_verification.fetch_item_detail")
    @mock.patch("scanner.listing_verification.requests.get")
    def test_mainland_auctions_is_unsupported_and_untouched(self, mock_get, mock_detail, mock_catalog, mock_division):
        result = verify_listing(MAINLAND_URL, _cache())

        self.assertEqual(result.status, "unsupported")
        mock_get.assert_not_called()
        mock_detail.assert_not_called()
        mock_catalog.assert_not_called()
        mock_division.assert_not_called()


class TestVerificationCache(unittest.TestCase):
    @mock.patch("scanner.listing_verification.fetch_category_items")
    def test_general_goods_catalog_fetched_once_for_repeated_slug(self, mock_catalog):
        mock_catalog.return_value = [{"item_id": "1", "price": 10.0, "pricing_status": "priced"}]
        cache = _cache()

        cache.general_goods_items("electronics/other")
        cache.general_goods_items("electronics/other")
        cache.general_goods_items("electronics/other")

        mock_catalog.assert_called_once_with("electronics/other", "NZ-Reseller-Scanner/1.0 (test)")

    @mock.patch("scanner.listing_verification.fetch_division")
    def test_vehicle_division_fetched_once_for_repeated_division(self, mock_division):
        mock_division.return_value = [{"item_id": "1", "price": 10.0}]
        cache = _cache()

        cache.vehicle_items("Cars")
        cache.vehicle_items("Cars")

        mock_division.assert_called_once_with("Cars", "NZ-Reseller-Scanner/1.0 (test)")


if __name__ == "__main__":
    unittest.main()
