import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import tempfile
import unittest

from scanner.discovery_report import (
    SCHEMA_VERSION,
    update_discovery_index,
    write_discovery_report,
)
from scanner.models import (
    ComparableEvidence,
    CostBreakdown,
    Opportunity,
    ProductIdentification,
    ResaleValuation,
)


def _opportunity(decision="BUY", flip_score=82):
    costs = CostBreakdown(
        purchase_price=100.0, buyer_premium=15.0, selling_fees=9.0, shipping=15.0, packaging=5.0
    )
    evidence = [
        ComparableEvidence(
            product="Widget", model="", condition="unknown", price=150.0, currency="NZD",
            source="Trade Me", url="https://www.trademe.co.nz/x",
            date_observed="2026-08-12T00:00:00+00:00", similarity_score=0.7,
            is_sold=True, evidence_type="SOLD",
        )
    ]
    valuation = ResaleValuation(
        quick_sale_low=120.0, quick_sale_high=140.0, normal=145.0, optimistic=160.0,
        confidence_pct=55.0, evidence=evidence, evidence_note="",
    )
    identification = ProductIdentification(brand="Acme", model="Widget", model_identified_confidently=True)
    o = Opportunity(
        title="Widget for sale", url="https://www.turners.co.nz/x", source="Turners",
        current_price=100.0, identification=identification, valuation=valuation, costs=costs,
    )
    o.expected_net_profit_low = 20.0
    o.expected_net_profit_high = 40.0
    o.roi_low_pct = 14.0
    o.roi_high_pct = 28.0
    o.max_buy_price = 130.0
    o.bidding_room = 30.0
    o.flip_score = flip_score
    o.flip_score_band = "STRONG"
    o.decision = decision
    o.decision_reasons = [f"Flip score {flip_score}/100"]
    return o


def _run_meta(**overrides):
    meta = {
        "run_timestamp": "2026-08-12T21:30:00+00:00",
        "mode": "discover",
        "queries_run": 15,
        "candidates_found": 5,
        "candidates_verified": 3,
        "candidates_verification_dropped": 2,
        "opportunity_count": 1,
        "decision_counts": {"BUY": 1},
    }
    meta.update(overrides)
    return meta


class TestWriteDiscoveryReport(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def test_writes_valid_json_with_schema_version(self):
        path, payload = write_discovery_report([_opportunity()], _run_meta(), reports_dir=self.tmpdir.name)

        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as f:
            on_disk = json.load(f)
        self.assertEqual(on_disk["schema_version"], SCHEMA_VERSION)
        self.assertEqual(on_disk, payload)

    def test_run_meta_passed_through_unchanged(self):
        meta = _run_meta(queries_run=9, candidates_found=7)
        _, payload = write_discovery_report([], meta, reports_dir=self.tmpdir.name)

        for key, value in meta.items():
            self.assertEqual(payload[key], value)

    def test_opportunity_fields_preserved_including_nested(self):
        o = _opportunity()
        _, payload = write_discovery_report([o], _run_meta(), reports_dir=self.tmpdir.name)
        row = payload["opportunities"][0]

        self.assertEqual(row["title"], o.title)
        self.assertEqual(row["url"], o.url)
        self.assertEqual(row["source"], o.source)
        self.assertEqual(row["decision"], o.decision)
        self.assertEqual(row["decision_reasons"], o.decision_reasons)
        self.assertEqual(row["flip_score"], o.flip_score)
        self.assertEqual(row["flip_score_band"], o.flip_score_band)
        self.assertEqual(row["max_buy_price"], o.max_buy_price)
        self.assertEqual(row["roi_low_pct"], o.roi_low_pct)
        self.assertEqual(row["identification"]["brand"], "Acme")
        self.assertEqual(row["identification"]["model_identified_confidently"], True)
        self.assertEqual(row["valuation"]["confidence_pct"], 55.0)
        self.assertEqual(row["valuation"]["quick_sale_low"], 120.0)
        self.assertEqual(len(row["valuation"]["evidence"]), 1)
        self.assertEqual(row["valuation"]["evidence"][0]["source"], "Trade Me")
        self.assertEqual(row["valuation"]["evidence"][0]["evidence_type"], "SOLD")
        self.assertEqual(row["costs"]["purchase_price"], 100.0)

    def test_resolved_property_values_included(self):
        o = _opportunity()
        _, payload = write_discovery_report([o], _run_meta(), reports_dir=self.tmpdir.name)
        row = payload["opportunities"][0]

        # These are @property on the dataclasses, not fields -- a bare
        # dataclasses.asdict() would omit them entirely.
        self.assertEqual(row["costs"]["total"], o.costs.total)
        self.assertEqual(row["costs"]["total_excluding_purchase"], o.costs.total_excluding_purchase)
        self.assertEqual(row["valuation"]["quick_sale_mid"], o.valuation.quick_sale_mid)
        self.assertEqual(row["costs"]["total"], 144.0)  # 100 + 15 + 9 + 15 + 5
        self.assertEqual(row["valuation"]["quick_sale_mid"], 130.0)  # (120 + 140) / 2

    def test_all_decision_types_serialize(self):
        decisions = ["BUY", "WATCH", "PASS", "PROFITABLE BUT CAPITAL RISK"]
        opportunities = [_opportunity(decision=d) for d in decisions]
        _, payload = write_discovery_report(
            opportunities, _run_meta(opportunity_count=4), reports_dir=self.tmpdir.name
        )

        self.assertEqual([row["decision"] for row in payload["opportunities"]], decisions)

    def test_none_fields_serialize_as_null_not_omitted(self):
        o = Opportunity(title="Unknown", url="https://example.co.nz/x", source="Turners", current_price=None)
        _, payload = write_discovery_report(
            [o], _run_meta(opportunity_count=1), reports_dir=self.tmpdir.name
        )
        row = payload["opportunities"][0]

        self.assertIn("current_price", row)
        self.assertIsNone(row["current_price"])
        self.assertIsNone(row["max_buy_price"])
        self.assertIsNone(row["valuation"]["quick_sale_mid"])

    def test_empty_opportunity_list_still_writes_valid_report(self):
        path, payload = write_discovery_report(
            [], _run_meta(opportunity_count=0, decision_counts={}), reports_dir=self.tmpdir.name
        )

        self.assertTrue(os.path.exists(path))
        self.assertEqual(payload["opportunities"], [])
        self.assertEqual(payload["opportunity_count"], 0)
        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)

    def test_filename_matches_discovery_prefix_and_extension(self):
        path, _ = write_discovery_report([], _run_meta(), reports_dir=self.tmpdir.name)
        basename = os.path.basename(path)

        self.assertTrue(basename.startswith("discovery_"))
        self.assertTrue(basename.endswith(".json"))
        self.assertNotIn("opportunities_", basename)  # never collide with the legacy CSV/XLSX naming


class TestUpdateDiscoveryIndex(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.index_path = os.path.join(self.tmpdir.name, "discovery_index.json")

    def test_creates_index_with_single_entry(self):
        payload = {
            "run_timestamp": "2026-08-12T09:00:00+00:00",
            "opportunity_count": 2,
            "decision_counts": {"BUY": 1, "PASS": 1},
        }
        index = update_discovery_index(
            "reports/discovery_20260812_0900.json", payload, index_path=self.index_path
        )

        self.assertEqual(index["count"], 1)
        self.assertEqual(index["reports"][0]["opportunity_count"], 2)
        self.assertEqual(index["reports"][0]["json"], "discovery_20260812_0900.json")
        self.assertEqual(index["reports"][0]["decision_counts"], {"BUY": 1, "PASS": 1})

    def test_appends_newest_first(self):
        p1 = {"run_timestamp": "2026-08-12T09:00:00+00:00", "opportunity_count": 1, "decision_counts": {}}
        p2 = {"run_timestamp": "2026-08-12T10:00:00+00:00", "opportunity_count": 3, "decision_counts": {}}
        update_discovery_index("reports/discovery_20260812_0900.json", p1, index_path=self.index_path)
        index = update_discovery_index("reports/discovery_20260812_1000.json", p2, index_path=self.index_path)

        self.assertEqual(index["count"], 2)
        self.assertEqual(index["reports"][0]["run_timestamp"], "2026-08-12T10:00:00+00:00")
        self.assertEqual(index["reports"][1]["run_timestamp"], "2026-08-12T09:00:00+00:00")

    def test_index_persisted_to_disk(self):
        payload = {"run_timestamp": "t", "opportunity_count": 0, "decision_counts": {}}
        update_discovery_index("reports/discovery_x.json", payload, index_path=self.index_path)

        with open(self.index_path, encoding="utf-8") as f:
            on_disk = json.load(f)
        self.assertEqual(on_disk["count"], 1)

    def test_corrupt_index_file_degrades_to_fresh_index_not_a_crash(self):
        with open(self.index_path, "w", encoding="utf-8") as f:
            f.write("{not valid json")

        payload = {"run_timestamp": "t", "opportunity_count": 0, "decision_counts": {}}
        index = update_discovery_index("reports/discovery_x.json", payload, index_path=self.index_path)

        self.assertEqual(index["count"], 1)


if __name__ == "__main__":
    unittest.main()
