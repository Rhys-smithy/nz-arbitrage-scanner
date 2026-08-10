import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest

from scanner.evidence import classify_evidence, convert_to_nzd


class TestClassifyEvidence(unittest.TestCase):
    def test_explicit_sold_flag_wins(self):
        self.assertEqual(
            classify_evidence("https://noelleeming.co.nz/x", is_explicitly_sold=True), "SOLD"
        )

    def test_retail_domain(self):
        self.assertEqual(classify_evidence("https://www.noelleeming.co.nz/product/x"), "RETAIL")

    def test_trademe_is_current_listing_by_default(self):
        self.assertEqual(classify_evidence("https://www.trademe.co.nz/a/x"), "CURRENT_LISTING")

    def test_ebay_with_sold_text_signal(self):
        result = classify_evidence(
            "https://www.ebay.com.au/itm/x", title="Nikon D90 - sold", description="completed listing"
        )
        self.assertEqual(result, "SOLD")

    def test_ebay_without_sold_text_is_current_listing(self):
        result = classify_evidence("https://www.ebay.com.au/itm/x", title="Nikon D90 for sale")
        self.assertEqual(result, "CURRENT_LISTING")

    def test_unknown_domain_is_other(self):
        self.assertEqual(classify_evidence("https://randomblog.example/post"), "OTHER")

    def test_empty_url(self):
        self.assertEqual(classify_evidence(""), "OTHER")


class TestCurrencyConversion(unittest.TestCase):
    def test_nzd_passthrough_not_marked_converted(self):
        price, converted = convert_to_nzd(100, "NZD")
        self.assertEqual(price, 100)
        self.assertFalse(converted)

    def test_aud_converted(self):
        price, converted = convert_to_nzd(100, "AUD")
        self.assertGreater(price, 100)  # AUD > NZD historically
        self.assertTrue(converted)

    def test_usd_converted(self):
        price, converted = convert_to_nzd(100, "USD")
        self.assertTrue(converted)
        self.assertGreater(price, 100)

    def test_unknown_currency_passthrough_unconverted(self):
        price, converted = convert_to_nzd(100, "XYZ")
        self.assertEqual(price, 100)
        self.assertFalse(converted)

    def test_none_price(self):
        price, converted = convert_to_nzd(None, "USD")
        self.assertIsNone(price)
        self.assertFalse(converted)

    def test_case_insensitive_currency_code(self):
        price1, _ = convert_to_nzd(100, "usd")
        price2, _ = convert_to_nzd(100, "USD")
        self.assertEqual(price1, price2)


if __name__ == "__main__":
    unittest.main()
