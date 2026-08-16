import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import tempfile
import unittest

from scanner.deal_queue_report import (
    DEFAULT_OUTPUT_PATH,
    load_latest_discovery_payload,
    render_latest_deal_queue,
)
from scanner.discovery_report import write_discovery_report, update_discovery_index
from scanner.models import ComparableEvidence, CostBreakdown, Opportunity, ProductIdentification, ResaleValuation


def _opportunity(decision="BUY", flip_score=82, url="https://www.turners.co.nz/x"):
    costs = CostBreakdown(purchase_price=100.0, buyer_premium=15.0, selling_fees=9.0, shipping=15.0, packaging=5.0)
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
        title="Widget for sale", url=url, source="Turners",
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
    if decision == "PROFITABLE BUT CAPITAL RISK":
        o.capital_concentration_pct = 62.0
    return o


class TestLoadLatestDiscoveryPayload(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.index_path = os.path.join(self.tmpdir.name, "discovery_index.json")

    def test_returns_none_when_no_index_exists(self):
        self.assertIsNone(
            load_latest_discovery_payload(index_path=self.index_path, reports_dir=self.tmpdir.name)
        )

    def test_returns_none_when_index_has_no_reports(self):
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump({"count": 0, "reports": []}, f)
        self.assertIsNone(
            load_latest_discovery_payload(index_path=self.index_path, reports_dir=self.tmpdir.name)
        )

    def test_returns_none_when_corrupt(self):
        with open(self.index_path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertIsNone(
            load_latest_discovery_payload(index_path=self.index_path, reports_dir=self.tmpdir.name)
        )

    def test_returns_exact_payload_of_newest_entry(self):
        run_meta_older = {
            "run_timestamp": "2026-08-12T09:00:00+00:00", "mode": "discover", "queries_run": 5,
            "candidates_found": 1, "candidates_verified": 1, "candidates_verification_dropped": 0,
            "opportunity_count": 1, "decision_counts": {"WATCH": 1},
        }
        run_meta_newer = {
            "run_timestamp": "2026-08-12T10:00:00+00:00", "mode": "discover", "queries_run": 5,
            "candidates_found": 1, "candidates_verified": 1, "candidates_verification_dropped": 0,
            "opportunity_count": 1, "decision_counts": {"BUY": 1},
        }
        path1, payload1 = write_discovery_report([_opportunity(decision="WATCH")], run_meta_older, reports_dir=self.tmpdir.name)
        update_discovery_index(path1, payload1, index_path=self.index_path)
        path2, payload2 = write_discovery_report([_opportunity(decision="BUY")], run_meta_newer, reports_dir=self.tmpdir.name)
        update_discovery_index(path2, payload2, index_path=self.index_path)

        loaded = load_latest_discovery_payload(index_path=self.index_path, reports_dir=self.tmpdir.name)

        self.assertEqual(loaded, payload2)
        self.assertEqual(loaded["decision_counts"], {"BUY": 1})


class TestRenderLatestDealQueue(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.index_path = os.path.join(self.tmpdir.name, "discovery_index.json")
        self.output_path = os.path.join(self.tmpdir.name, "deal_queue.html")

    def _persist_run(self, opportunities, **meta_overrides):
        meta = {
            "run_timestamp": "2026-08-12T21:30:00+00:00", "mode": "discover", "queries_run": 15,
            "candidates_found": 5, "candidates_verified": 3, "candidates_verification_dropped": 2,
            "opportunity_count": len(opportunities),
            "decision_counts": {},
        }
        meta.update(meta_overrides)
        path, payload = write_discovery_report(opportunities, meta, reports_dir=self.tmpdir.name)
        update_discovery_index(path, payload, index_path=self.index_path)
        return payload

    def test_returns_none_when_no_run_persisted_yet(self):
        result = render_latest_deal_queue(
            index_path=self.index_path, reports_dir=self.tmpdir.name, output_path=self.output_path
        )
        self.assertIsNone(result)
        self.assertFalse(os.path.exists(self.output_path))

    def test_writes_html_file_and_returns_path(self):
        self._persist_run([_opportunity()], decision_counts={"BUY": 1})
        result = render_latest_deal_queue(
            index_path=self.index_path, reports_dir=self.tmpdir.name, output_path=self.output_path
        )
        self.assertEqual(result, self.output_path)
        self.assertTrue(os.path.exists(self.output_path))
        with open(self.output_path, encoding="utf-8") as f:
            html = f.read()
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("Deal queue", html)

    def test_embedded_json_round_trips_exactly_to_source_payload(self):
        payload = self._persist_run(
            [_opportunity(decision="BUY"), _opportunity(decision="PASS", url="https://www.turners.co.nz/y")],
            decision_counts={"BUY": 1, "PASS": 1},
        )
        render_latest_deal_queue(index_path=self.index_path, reports_dir=self.tmpdir.name, output_path=self.output_path)

        with open(self.output_path, encoding="utf-8") as f:
            html = f.read()
        start_marker = '<script id="discovery-report-data" type="application/json">'
        end_marker = "</script>"
        start = html.index(start_marker) + len(start_marker)
        end = html.index(end_marker, start)
        embedded = json.loads(html[start:end])

        self.assertEqual(embedded, payload)
        self.assertEqual(embedded["opportunities"][0]["decision"], "BUY")
        self.assertEqual(embedded["opportunities"][0]["costs"]["total"], payload["opportunities"][0]["costs"]["total"])
        self.assertEqual(
            embedded["opportunities"][0]["valuation"]["quick_sale_mid"],
            payload["opportunities"][0]["valuation"]["quick_sale_mid"],
        )

    def test_zero_opportunity_run_still_renders_valid_page(self):
        self._persist_run([], decision_counts={})
        result = render_latest_deal_queue(
            index_path=self.index_path, reports_dir=self.tmpdir.name, output_path=self.output_path
        )
        self.assertIsNotNone(result)
        with open(self.output_path, encoding="utf-8") as f:
            html = f.read()
        self.assertIn('"opportunities":[]', html.replace(" ", ""))

    def test_special_characters_in_title_do_not_break_json_embedding(self):
        o = _opportunity()
        o.title = 'Widget "deluxe" <script>alert(1)</script> & friends'
        self._persist_run([o], decision_counts={"BUY": 1})
        render_latest_deal_queue(index_path=self.index_path, reports_dir=self.tmpdir.name, output_path=self.output_path)

        with open(self.output_path, encoding="utf-8") as f:
            html = f.read()
        start_marker = '<script id="discovery-report-data" type="application/json">'
        end_marker = "</script>"
        start = html.index(start_marker) + len(start_marker)
        end = html.index(end_marker, start)
        embedded = json.loads(html[start:end])
        self.assertEqual(embedded["opportunities"][0]["title"], o.title)
        # No unescaped literal "</script>" from user data can appear before
        # the JSON block's own closing tag (which would truncate the JSON
        # payload when parsed by the browser).
        self.assertNotIn("</script>alert", html[start:end])

    def test_default_output_path_matches_reports_dir_convention(self):
        self.assertTrue(DEFAULT_OUTPUT_PATH.endswith(os.path.join("reports", "deal_queue.html")))


if __name__ == "__main__":
    unittest.main()
