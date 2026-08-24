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


def _opportunity(
    decision="BUY",
    flip_score=82,
    # Phase 4B.2 follow-up (persistence port): defaults match Opportunity's
    # own dataclass defaults exactly, so every existing call to
    # _opportunity() below (none of which pass these) is unaffected --
    # only TestAuctionMetadataFieldsPersisted below exercises non-default
    # values.
    price_type=None,
    buy_now_price=None,
    reserve_status=None,
    closing_date="",
    starts_on="",
):
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
        price_type=price_type, buy_now_price=buy_now_price, reserve_status=reserve_status,
        closing_date=closing_date, starts_on=starts_on,
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

    def test_filename_includes_seconds_so_two_runs_in_the_same_minute_do_not_collide(self):
        # Regression guard: this filename used to be minute-granularity
        # only (discovery_%Y%m%d_%H%M.json). Reproduced directly: two real
        # discover-mode runs finishing ~8s apart landed on the exact same
        # filename, and the second run's write silently overwrote the
        # first's -- discovery_index.json was left with two entries
        # (different opportunity_count/decision_counts) both pointing at
        # the one file that now only held the second run's data. Seconds
        # granularity (combined with scanner/scan_lock.py, which now
        # prevents two discover-mode runs from overlapping in time at all)
        # closes this.
        path, _ = write_discovery_report([], _run_meta(), reports_dir=self.tmpdir.name)
        basename = os.path.basename(path)
        # discovery_YYYYMMDD_HHMMSS.json -- the timestamp segment after the
        # second underscore must be 6 digits (HHMMSS), not 4 (HHMM).
        timestamp_segment = basename[len("discovery_"):-len(".json")].split("_")[1]
        self.assertEqual(len(timestamp_segment), 6, basename)


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


class TestAuctionMetadataFieldsPersisted(unittest.TestCase):
    """Phase 4B.2 follow-up (persistence port): the 5 auction-state fields
    (price_type + the 4 added alongside this persistence work -- see
    scanner/models.py) must survive the Opportunity -> JSON round-trip
    unchanged, since they're exactly what a human needs to see to inspect
    *why* a decision was made (e.g. a starting_bid item that was correctly
    denied profit/ROI). This module must not reinterpret or invent any of
    them -- it's a passthrough via dataclasses.asdict(), same as every
    other Opportunity field."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def test_all_five_metadata_fields_round_trip_through_json(self):
        o = _opportunity(
            price_type="current_bid",
            buy_now_price=17400.0,
            reserve_status="Reserve Met",
            closing_date="12 Aug 26",
            starts_on="",
        )
        _, payload = write_discovery_report([o], _run_meta(), reports_dir=self.tmpdir.name)
        row = payload["opportunities"][0]

        self.assertEqual(row["price_type"], "current_bid")
        self.assertEqual(row["buy_now_price"], 17400.0)
        self.assertEqual(row["reserve_status"], "Reserve Met")
        self.assertEqual(row["closing_date"], "12 Aug 26")
        self.assertEqual(row["starts_on"], "")

    def test_starting_bid_metadata_round_trips_alongside_suppressed_profit(self):
        # Exactly the case this persistence layer exists to make
        # inspectable: a starting_bid item whose profit/ROI were correctly
        # suppressed by valuation.py (unmodified by this port) -- the
        # metadata explaining *why* must still be present in the report.
        o = _opportunity(
            price_type="starting_bid", reserve_status="No Reserve", closing_date="20 Aug 26",
        )
        o.expected_net_profit_low = None
        o.expected_net_profit_high = None
        o.roi_low_pct = None
        o.roi_high_pct = None
        _, payload = write_discovery_report([o], _run_meta(), reports_dir=self.tmpdir.name)
        row = payload["opportunities"][0]

        self.assertEqual(row["price_type"], "starting_bid")
        self.assertEqual(row["reserve_status"], "No Reserve")
        self.assertIsNone(row["expected_net_profit_low"])
        self.assertIsNone(row["roi_low_pct"])

    def test_missing_metadata_fields_serialize_as_default_not_invented(self):
        # Non-Turners sources (e.g. a Tavily/web-search candidate) never
        # populate these -- must come through as their real defaults
        # (None/None/None/""/""), never a fabricated placeholder value.
        o = _opportunity()  # no metadata kwargs -- Opportunity's own defaults
        _, payload = write_discovery_report([o], _run_meta(), reports_dir=self.tmpdir.name)
        row = payload["opportunities"][0]

        self.assertIsNone(row["price_type"])
        self.assertIsNone(row["buy_now_price"])
        self.assertIsNone(row["reserve_status"])
        self.assertEqual(row["closing_date"], "")
        self.assertEqual(row["starts_on"], "")

    def test_vehicle_style_metadata_reserve_fields_false_not_fabricated(self):
        # Turners Vehicles division: price_type/buy_now_price are real, but
        # reserve_status/closing_date/starts_on are never scraped for that
        # division (see scanner/search/auction_search.py) -- must persist
        # as their real falsy defaults, not silently inherit General Goods'
        # values or crash.
        o = _opportunity(price_type="buy_now", buy_now_price=17400.0)
        _, payload = write_discovery_report([o], _run_meta(), reports_dir=self.tmpdir.name)
        row = payload["opportunities"][0]

        self.assertEqual(row["price_type"], "buy_now")
        self.assertEqual(row["buy_now_price"], 17400.0)
        self.assertIsNone(row["reserve_status"])
        self.assertEqual(row["closing_date"], "")
        self.assertEqual(row["starts_on"], "")


if __name__ == "__main__":
    unittest.main()
