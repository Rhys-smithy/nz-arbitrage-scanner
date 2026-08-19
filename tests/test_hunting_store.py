import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import tempfile
import unittest

from scanner.hunting_store import (
    get,
    load_hunting_state,
    make_key,
    save_hunting_state,
    star,
    unstar,
    update_notes,
    update_target_offer,
)


class TestMakeKey(unittest.TestCase):
    def test_dedupes_by_canonical_url_same_as_discovery_store(self):
        # Reuses scanner.search.util.canonicalize_url -- tracking params,
        # scheme, and trailing slash differences must all collapse to one key.
        k1 = make_key("Turners", "https://www.turners.co.nz/x/123?utm_source=fb")
        k2 = make_key("Turners", "http://www.turners.co.nz/x/123/?utm_source=twitter")
        self.assertEqual(k1, k2)

    def test_different_sources_same_url_are_different_keys(self):
        k1 = make_key("Turners", "https://example.com/x")
        k2 = make_key("Thorntons", "https://example.com/x")
        self.assertNotEqual(k1, k2)

    def test_different_urls_are_different_keys(self):
        k1 = make_key("Turners", "https://example.com/x")
        k2 = make_key("Turners", "https://example.com/y")
        self.assertNotEqual(k1, k2)


class TestLoadSaveHuntingState(unittest.TestCase):
    def test_load_missing_file_returns_empty_dict(self):
        self.assertEqual(load_hunting_state("/tmp/definitely_does_not_exist_hunting_12345.json"), {})

    def test_load_corrupt_file_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "hunting_state.json")
            with open(path, "w") as f:
                f.write("{not valid json")
            self.assertEqual(load_hunting_state(path), {})

    def test_load_non_dict_json_returns_empty_dict(self):
        # A malformed-but-valid-JSON file (e.g. a JSON array) must not be
        # mistaken for a valid state dict and passed through as-is.
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "hunting_state.json")
            with open(path, "w") as f:
                json.dump([1, 2, 3], f)
            self.assertEqual(load_hunting_state(path), {})

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "hunting_state.json")
            state = {}
            star(state, "Turners", "https://example.com/x", notes="watch this one")
            save_hunting_state(state, path)
            loaded = load_hunting_state(path)
            self.assertEqual(loaded, state)


class TestStar(unittest.TestCase):
    def test_star_creates_hunting_record(self):
        state = {}
        entry = star(state, "Turners", "https://example.com/x")
        self.assertEqual(entry["status"], "hunting")
        self.assertEqual(entry["source"], "Turners")
        self.assertIn("starred_at", entry)
        self.assertIsNone(entry["target_offer_override"])
        self.assertEqual(entry["notes"], "")
        self.assertEqual(len(state), 1)

    def test_star_is_keyed_by_canonical_url_not_raw_url(self):
        state = {}
        star(state, "Turners", "https://www.turners.co.nz/x?utm_source=fb")
        star(state, "Turners", "https://www.turners.co.nz/x?utm_source=twitter")
        # Second call updates the same record rather than creating a second one.
        self.assertEqual(len(state), 1)

    def test_restarring_preserves_original_starred_at(self):
        state = {}
        star(state, "Turners", "https://example.com/x")
        first_key = make_key("Turners", "https://example.com/x")
        original_starred_at = state[first_key]["starred_at"]

        star(state, "Turners", "https://example.com/x")
        self.assertEqual(state[first_key]["starred_at"], original_starred_at)

    def test_restarring_without_notes_preserves_existing_notes(self):
        state = {}
        star(state, "Turners", "https://example.com/x", notes="original note")
        star(state, "Turners", "https://example.com/x")  # re-star, no notes passed
        entry = get(state, "Turners", "https://example.com/x")
        self.assertEqual(entry["notes"], "original note")

    def test_star_with_target_offer_override(self):
        state = {}
        entry = star(state, "Turners", "https://example.com/x", target_offer_override=85.5)
        self.assertEqual(entry["target_offer_override"], 85.5)


class TestUnstar(unittest.TestCase):
    def test_unstar_removes_record(self):
        state = {}
        star(state, "Turners", "https://example.com/x")
        removed = unstar(state, "Turners", "https://example.com/x")
        self.assertTrue(removed)
        self.assertEqual(state, {})

    def test_unstar_nonexistent_record_returns_false(self):
        state = {}
        removed = unstar(state, "Turners", "https://example.com/never-starred")
        self.assertFalse(removed)
        self.assertEqual(state, {})

    def test_unstar_then_restar_gets_fresh_starred_at(self):
        state = {}
        star(state, "Turners", "https://example.com/x")
        unstar(state, "Turners", "https://example.com/x")
        entry = star(state, "Turners", "https://example.com/x")
        # No tombstone was kept -- this is indistinguishable from a
        # first-time star, by design (see hunting_store.unstar docstring).
        self.assertIn("starred_at", entry)
        self.assertEqual(len(state), 1)


class TestUpdateNotesAndTargetOffer(unittest.TestCase):
    def test_update_notes_on_existing_record(self):
        state = {}
        star(state, "Turners", "https://example.com/x")
        entry = update_notes(state, "Turners", "https://example.com/x", "call the seller")
        self.assertEqual(entry["notes"], "call the seller")

    def test_update_notes_on_non_hunted_listing_is_noop(self):
        state = {}
        result = update_notes(state, "Turners", "https://example.com/never-starred", "note")
        self.assertIsNone(result)
        self.assertEqual(state, {})

    def test_update_target_offer_on_existing_record(self):
        state = {}
        star(state, "Turners", "https://example.com/x")
        entry = update_target_offer(state, "Turners", "https://example.com/x", 120.0)
        self.assertEqual(entry["target_offer_override"], 120.0)

    def test_update_target_offer_can_clear_to_none(self):
        state = {}
        star(state, "Turners", "https://example.com/x", target_offer_override=120.0)
        entry = update_target_offer(state, "Turners", "https://example.com/x", None)
        self.assertIsNone(entry["target_offer_override"])

    def test_update_target_offer_on_non_hunted_listing_is_noop(self):
        state = {}
        result = update_target_offer(state, "Turners", "https://example.com/never-starred", 50.0)
        self.assertIsNone(result)
        self.assertEqual(state, {})

    def test_target_offer_override_is_independent_field_from_scanner_max_buy(self):
        # hunting_store has no concept of max_buy_price at all -- it must
        # never read, write, or otherwise reference scanner.models.Opportunity
        # fields. This test asserts the *shape* of a hunting record contains
        # only user-state fields, so a future change can't accidentally
        # smuggle scanner-computed fields into this store.
        state = {}
        entry = star(state, "Turners", "https://example.com/x", target_offer_override=100.0)
        self.assertNotIn("max_buy_price", entry)
        self.assertEqual(
            set(entry.keys()),
            {"source", "url", "status", "starred_at", "notes", "target_offer_override"},
        )


if __name__ == "__main__":
    unittest.main()
