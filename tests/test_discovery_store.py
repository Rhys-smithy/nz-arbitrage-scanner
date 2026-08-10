import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tempfile
import unittest

from scanner.discovery_store import load_discovered, record_sightings, save_discovered
from scanner.search.base import SearchResult


def _result(url):
    return SearchResult(title="x", url=url, price=None, currency="NZD", source="s")


class TestDiscoveryStore(unittest.TestCase):
    def test_new_listing_recorded_as_first_and_last_seen(self):
        discovered = {}
        new_urls = record_sightings([_result("https://a.com/x")], discovered)
        self.assertEqual(len(new_urls), 1)
        entry = next(iter(discovered.values()))
        self.assertEqual(entry["first_seen"], entry["last_seen"])

    def test_repeat_listing_updates_last_seen_only(self):
        discovered = {}
        record_sightings([_result("https://a.com/x")], discovered)
        first_seen = next(iter(discovered.values()))["first_seen"]

        new_urls = record_sightings([_result("https://a.com/x")], discovered)
        self.assertEqual(len(new_urls), 0)  # not newly seen second time
        entry = next(iter(discovered.values()))
        self.assertEqual(entry["first_seen"], first_seen)

    def test_dedupes_by_canonical_url(self):
        discovered = {}
        record_sightings([_result("https://a.com/x?utm_source=fb")], discovered)
        new_urls = record_sightings([_result("https://a.com/x?utm_source=twitter")], discovered)
        self.assertEqual(len(new_urls), 0)
        self.assertEqual(len(discovered), 1)

    def test_load_missing_file_returns_empty_dict(self):
        self.assertEqual(load_discovered("/tmp/definitely_does_not_exist_12345.json"), {})

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "discovered.json")
            discovered = {}
            record_sightings([_result("https://a.com/x")], discovered)
            save_discovered(discovered, path)
            loaded = load_discovered(path)
            self.assertEqual(loaded, discovered)

    def test_load_corrupt_file_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "discovered.json")
            with open(path, "w") as f:
                f.write("{not valid json")
            self.assertEqual(load_discovered(path), {})


if __name__ == "__main__":
    unittest.main()
