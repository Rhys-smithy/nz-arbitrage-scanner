import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest

from scanner.query_generator import generate_comparable_queries, generate_discovery_queries


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
