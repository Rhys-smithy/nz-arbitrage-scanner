import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest

from scanner.search.base import SearchResult
from scanner.search.util import (
    canonicalize_url,
    dedupe_results,
    identify_marketplace,
    is_individual_listing_url,
)


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


class TestIsIndividualListingUrl(unittest.TestCase):
    # Real listing pages (actual URL shapes, verified against live sites).
    def test_trademe_listing_passes(self):
        self.assertTrue(is_individual_listing_url(
            "https://www.trademe.co.nz/a/marketplace/electronics-photography/"
            "digital-cameras/digital-slr/nikon/listing/6068741860?rsqid=abc"
        ))

    def test_ebay_itm_passes(self):
        self.assertTrue(is_individual_listing_url("https://www.ebay.com/itm/272847582919"))

    def test_ebay_itm_with_title_slug_passes(self):
        self.assertTrue(is_individual_listing_url("https://www.ebay.com.au/itm/Some-Camera-Title/272847582919"))

    def test_facebook_marketplace_item_passes(self):
        self.assertTrue(is_individual_listing_url("https://www.facebook.com/marketplace/item/1234567890123/"))

    def test_turners_general_goods_item_passes(self):
        self.assertTrue(is_individual_listing_url(
            "https://www.turners.co.nz/General-Goods/Search/electronics/cameras/123456/"
        ))

    def test_turners_vehicle_detail_passes(self):
        self.assertTrue(is_individual_listing_url("https://www.turners.co.nz/Vehicles/Toyota/Corolla/654321"))

    def test_thorntons_auction_detail_passes(self):
        self.assertTrue(is_individual_listing_url("https://www.thorntons.net.nz/auctions/detail/7890"))

    def test_mainland_auctions_lot_passes(self):
        self.assertTrue(is_individual_listing_url("https://www.mainlandauctions.nz/auctions/some-lot-slug"))

    # Category / browse / search pages on the SAME recognised domains --
    # these are the ones that were slipping through before the fix.
    def test_trademe_category_page_rejected(self):
        self.assertFalse(is_individual_listing_url(
            "https://www.trademe.co.nz/a/marketplace/electronics-photography/digital-cameras/digital-slr/nikon"
        ))

    def test_trademe_shop_search_page_rejected(self):
        self.assertFalse(is_individual_listing_url("https://www.trademe.co.nz/a/marketplace/s/camera/k1c0-124"))

    def test_ebay_search_page_rejected(self):
        self.assertFalse(is_individual_listing_url("https://www.ebay.com/sch/i.html?_nkw=camera"))

    def test_facebook_marketplace_category_rejected(self):
        self.assertFalse(is_individual_listing_url("https://www.facebook.com/marketplace/category/electronics"))

    def test_mainland_auctions_home_rejected(self):
        self.assertFalse(is_individual_listing_url("https://www.mainlandauctions.nz/auctions"))

    # Non-marketplace domains -- excluded outright regardless of URL shape.
    def test_youtube_rejected(self):
        self.assertFalse(is_individual_listing_url("https://www.youtube.com/watch?v=abc123"))

    def test_etsy_rejected(self):
        self.assertFalse(is_individual_listing_url("https://www.etsy.com/nz/c/electronics/cameras"))

    def test_retailer_rejected(self):
        self.assertFalse(is_individual_listing_url("https://www.noelleeming.co.nz/shop/product/camera-123"))

    def test_news_site_rejected(self):
        self.assertFalse(is_individual_listing_url("https://www.stuff.co.nz/technology/camera-review"))

    def test_empty_url_rejected(self):
        self.assertFalse(is_individual_listing_url(""))


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
