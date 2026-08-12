import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest

from scanner.query_generator import (
    allocate_discovery_queries,
    generate_comparable_queries,
    generate_discovery_queries,
)


class TestGenerateDiscoveryQueries(unittest.TestCase):
    def test_generates_bare_and_concept_queries(self):
        queries = generate_discovery_queries(["Nintendo Switch"], ["bundle", "lot"])
        self.assertIn("Nintendo Switch NZ", queries)
        self.assertIn("Nintendo Switch bundle NZ", queries)
        self.assertIn("Nintendo Switch lot NZ", queries)

    def test_includes_marketplace_site_queries(self):
        queries = generate_discovery_queries(["Nintendo Switch"], [], marketplace_sites=["site:trademe.co.nz"])
        self.assertIn("site:trademe.co.nz Nintendo Switch", queries)

    def test_no_duplicate_queries(self):
        queries = generate_discovery_queries(["A", "A"], ["bundle"])
        self.assertEqual(len(queries), len(set(queries)))

    def test_empty_products_gives_empty_queries(self):
        self.assertEqual(generate_discovery_queries([], ["bundle"]), [])

    def test_can_disable_bare_product_query(self):
        queries = generate_discovery_queries(["X"], ["bundle"], include_bare_product=False)
        self.assertNotIn("X NZ", queries)
        self.assertIn("X bundle NZ", queries)


class TestAllocateDiscoveryQueries(unittest.TestCase):
    """Regression coverage for two known issues:

    Run #23: generate_discovery_queries() is product-major, so with a tight
    max_queries budget the first product consumed the entire budget and
    every other configured product got zero queries.
    allocate_discovery_queries() must round-robin instead.

    Rebalance issue (flagged in PR #5 review, PROJECT_STATE.md): the
    original round-robin put each product's bare-product query (no bargain
    signal) first, so round 0 -- guaranteed budget -- was 100% bare-product
    queries. At 12 products / 15 budget that's 12 of 15 slots (80%) on the
    weakest query shape, and only 3 slots ever reached a concept query --
    always the same 3 products (config order never changes) and always the
    same 1 concept ("bundle", first in config order). 12 of 13 configured
    bargain-signal concepts and 9 of 12 products never got a concept query
    at all. Fixed by prioritising concept queries, capping bare-product to
    a small configurable floor of the budget, and rotating product/concept
    order by a `seed` so coverage cycles across runs instead of always
    favouring whatever's first in config.json."""

    PRODUCTS_12 = [
        "Nintendo Switch", "Canon camera", "Nikon camera", "Carrera Digital 132",
        "Traxxas", "Tamiya", "LEGO", "DJI drone", "GoPro", "Dyson vacuum",
        "KitchenAid mixer", "Makita tools",
    ]
    CONCEPTS_13 = [
        "bundle", "lot", "collection", "clearance", "moving house", "unwanted",
        "don't know", "untested", "parts", "garage", "estate", "must sell",
        "make an offer",
    ]

    def test_every_product_gets_at_least_one_query_at_run23_scale(self):
        # This is the exact shape that triggered the Run #23 bug: 12
        # products x 13 concepts with max_queries_per_run=15 -- product #1
        # alone used to generate 14 queries (1 bare + 13 concepts), leaving
        # nothing for products 2-12.
        queries = allocate_discovery_queries(self.PRODUCTS_12, self.CONCEPTS_13, max_queries=15)
        self.assertEqual(len(queries), 15)
        for product in self.PRODUCTS_12:
            self.assertTrue(
                any(product in q for q in queries),
                f"{product!r} got zero queries out of the 15-query budget",
            )

    def test_concept_queries_prioritised_over_bare_product(self):
        # At 12 products / 15 budget / default 15% bare floor: round 0 is
        # now the first concept ("bundle") for all 12 products (12 slots),
        # 1 leftover concept slot goes to product #1's second concept
        # ("lot"), and only 2 of 15 slots (the 15% floor, rounded) go to
        # bare-product queries -- a full inversion of the pre-fix 12:3
        # bare:concept split.
        queries = allocate_discovery_queries(self.PRODUCTS_12, self.CONCEPTS_13, max_queries=15)
        concept_queries = [q for q in queries if any(f" {c} " in f" {q} " for c in self.CONCEPTS_13)]
        bare_queries = [q for q in queries if q not in concept_queries]
        self.assertEqual(len(concept_queries), 13)
        self.assertEqual(len(bare_queries), 2)
        for product in self.PRODUCTS_12:
            self.assertIn(f"{product} bundle NZ", queries)

    def test_round_robins_one_query_per_product_per_round(self):
        queries = allocate_discovery_queries(["A", "B", "C"], ["bundle"], max_queries=6)
        # Concept queries (round 0) come first for every product, then the
        # bare-product floor (~15% of 6, floored to a minimum of 1) fills
        # the rest, rotating through the same product order.
        self.assertEqual(
            queries,
            ["A bundle NZ", "B bundle NZ", "C bundle NZ", "A NZ", "B NZ", "C NZ"],
        )

    def test_respects_max_queries_cap(self):
        queries = allocate_discovery_queries(self.PRODUCTS_12, self.CONCEPTS_13, max_queries=5)
        self.assertEqual(len(queries), 5)

    def test_no_duplicate_queries(self):
        queries = allocate_discovery_queries(["A", "A"], ["bundle"], max_queries=10)
        self.assertEqual(len(queries), len(set(queries)))

    def test_empty_products_gives_empty_queries(self):
        self.assertEqual(allocate_discovery_queries([], ["bundle"], max_queries=15), [])

    def test_zero_or_negative_budget_gives_empty_queries(self):
        self.assertEqual(allocate_discovery_queries(["A"], ["bundle"], max_queries=0), [])
        self.assertEqual(allocate_discovery_queries(["A"], ["bundle"], max_queries=-1), [])

    def test_fewer_products_than_budget_uses_remaining_on_concepts(self):
        # 2 products, budget of 5 -- concept round-robin exhausts both
        # concepts for both products (4 queries: A/B bundle, A/B lot), then
        # the 1-query bare floor takes the last slot.
        queries = allocate_discovery_queries(["A", "B"], ["bundle", "lot"], max_queries=5)
        self.assertEqual(len(queries), 5)
        self.assertIn("A bundle NZ", queries)
        self.assertIn("B bundle NZ", queries)
        self.assertIn("A lot NZ", queries)
        self.assertIn("B lot NZ", queries)
        self.assertIn("A NZ", queries)

    def test_bare_product_floor_is_small_default_share_of_budget(self):
        # ~15% of 15 = 2.25 -> rounds to 2 bare-product queries by default.
        queries = allocate_discovery_queries(self.PRODUCTS_12, self.CONCEPTS_13, max_queries=15)
        bare_only = [q for q in queries if q.endswith(" NZ") and not any(f" {c} " in f" {q} " for c in self.CONCEPTS_13)]
        self.assertEqual(len(bare_only), 2)

    def test_bare_product_min_ratio_is_configurable_and_can_disable(self):
        queries = allocate_discovery_queries(
            self.PRODUCTS_12, self.CONCEPTS_13, max_queries=15, bare_product_min_ratio=0.0
        )
        bare_only = [q for q in queries if q.endswith(" NZ") and not any(f" {c} " in f" {q} " for c in self.CONCEPTS_13)]
        self.assertEqual(bare_only, [])

        queries = allocate_discovery_queries(
            self.PRODUCTS_12, self.CONCEPTS_13, max_queries=15, bare_product_min_ratio=0.5
        )
        bare_only = [q for q in queries if q.endswith(" NZ") and not any(f" {c} " in f" {q} " for c in self.CONCEPTS_13)]
        self.assertGreater(len(bare_only), 2)

    def test_seed_rotates_which_concept_gets_priority(self):
        # Same inputs, different seed -> a different concept fills the
        # guaranteed first round instead of always "bundle". This is what
        # makes coverage cycle across runs instead of camping on whichever
        # concept happens to be first in config.json.
        seed0 = allocate_discovery_queries(
            ["A", "B", "C"], ["bundle", "lot", "collection"], max_queries=3, include_bare_product=False, seed=0
        )
        seed1 = allocate_discovery_queries(
            ["A", "B", "C"], ["bundle", "lot", "collection"], max_queries=3, include_bare_product=False, seed=1
        )
        self.assertEqual(seed0, ["A bundle NZ", "B bundle NZ", "C bundle NZ"])
        self.assertTrue(all("lot" in q for q in seed1))
        self.assertNotEqual(seed0, seed1)

    def test_seed_rotates_which_products_get_scarce_budget(self):
        # 4 products but only budget for 2 -- without rotation, products C
        # and D would never get a query, ever (the exact staleness bug this
        # fix addresses). Different seeds must reach different products.
        seed0 = allocate_discovery_queries(["A", "B", "C", "D"], ["bundle"], max_queries=2, include_bare_product=False, seed=0)
        seed2 = allocate_discovery_queries(["A", "B", "C", "D"], ["bundle"], max_queries=2, include_bare_product=False, seed=2)
        self.assertEqual(seed0, ["A bundle NZ", "B bundle NZ"])
        self.assertEqual(seed2, ["C bundle NZ", "D bundle NZ"])


class TestGenerateComparableQueries(unittest.TestCase):
    def test_generates_expected_query_shapes(self):
        queries = generate_comparable_queries("Carrera Digital 132 GT Championship")
        self.assertTrue(any("sold" in q for q in queries))
        self.assertTrue(any("ebay sold" in q for q in queries))
        self.assertTrue(any(q.startswith("site:trademe.co.nz") for q in queries))
        self.assertTrue(all('"Carrera Digital 132 GT Championship"' in q for q in queries))

    def test_empty_title_gives_empty_queries(self):
        self.assertEqual(generate_comparable_queries(""), [])
        self.assertEqual(generate_comparable_queries("   "), [])


if __name__ == "__main__":
    unittest.main()
