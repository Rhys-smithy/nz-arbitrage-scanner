import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest

from scanner.search_stats import extract_concept_from_query, record_query_concept_result


class TestRecordQueryConceptResult(unittest.TestCase):
    def test_increments_opportunities(self):
        stats = {}
        record_query_concept_result(stats, "bundle", "WATCH")
        self.assertEqual(stats["bundle"]["opportunities"], 1)
        self.assertEqual(stats["bundle"]["profitable"], 0)

    def test_buy_counts_as_profitable(self):
        stats = {}
        record_query_concept_result(stats, "bundle", "BUY")
        self.assertEqual(stats["bundle"]["profitable"], 1)

    def test_capital_risk_counts_as_profitable(self):
        stats = {}
        record_query_concept_result(stats, "bundle", "PROFITABLE BUT CAPITAL RISK")
        self.assertEqual(stats["bundle"]["profitable"], 1)

    def test_pass_does_not_count_as_profitable(self):
        stats = {}
        record_query_concept_result(stats, "bundle", "PASS")
        self.assertEqual(stats["bundle"]["opportunities"], 1)
        self.assertEqual(stats["bundle"]["profitable"], 0)

    def test_accumulates_across_calls(self):
        stats = {}
        record_query_concept_result(stats, "bundle", "BUY")
        record_query_concept_result(stats, "bundle", "PASS")
        self.assertEqual(stats["bundle"]["opportunities"], 2)
        self.assertEqual(stats["bundle"]["profitable"], 1)


class TestExtractConceptFromQuery(unittest.TestCase):
    def test_finds_matching_concept(self):
        concept = extract_concept_from_query("Nintendo Switch bundle NZ", ["bundle", "lot"])
        self.assertEqual(concept, "bundle")

    def test_no_match_returns_none(self):
        concept = extract_concept_from_query("Nintendo Switch NZ", ["bundle", "lot"])
        self.assertIsNone(concept)

    def test_case_insensitive(self):
        concept = extract_concept_from_query("Nintendo Switch BUNDLE NZ", ["bundle"])
        self.assertEqual(concept, "bundle")


if __name__ == "__main__":
    unittest.main()
