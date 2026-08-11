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
    """Regression coverage for the Run #23 bug: generate_discovery_queries()
    is product-major, so with a tight max_queries budget the first product
    consumed the entire budget and every other configured product got zero
    queries. allocate_discovery_queries() must round-robin instead."""

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
        # This is the exact shape that triggered the bug: 12 products x 13
        # concepts with max_queries_per_run=15 -- product #1 alone used to
        # generate 14 queries (1 bare + 13 concepts), leaving nothing for
        # products 2-12.
        queries = allocate_discovery_queries(self.PRODUCTS_12, self.CONCEPTS_13, max_queries=15)
        self.assertEqual(len(queries), 15)
        for product in self.PRODUCTS_12:
            self.assertTrue(
                any(product in q for q in queries),
                f"{product!r} got zero queries out of the 15-query budget",
            )

    def test_round_robins_one_query_per_product_per_round(self):
        queries = allocate_discovery_queries(["A", "B", "C"], ["bundle"], max_queries=6)
        # Round 0: bare product for A, B, C. Round 1: "bundle" concept for A, B, C.
        self.assertEqual(
            queries,
            ["A NZ", "B NZ", "C NZ", "A bundle NZ", "B bundle NZ", "C bundle NZ"],
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
        # 2 products, budget of 5 -- round 0 uses 2 (bare), round 1 uses up
        # to 2 more (first concept each), leaving 1 more for round 2.
        queries = allocate_discovery_queries(["A", "B"], ["bundle", "lot"], max_queries=5)
        self.assertEqual(len(queries), 5)
        self.assertIn("A NZ", queries)
        self.assertIn("B NZ", queries)


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
