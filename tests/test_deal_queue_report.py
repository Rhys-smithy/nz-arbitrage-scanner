import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import csv
import json
import tempfile
import unittest

from scanner.deal_queue_report import (
    DEFAULT_OUTPUT_PATH,
    load_latest_discovery_payload,
    load_latest_legacy_scan_payload,
    render_latest_deal_queue,
)
from scanner.discovery_report import write_discovery_report, update_discovery_index
from scanner.models import ComparableEvidence, CostBreakdown, Opportunity, ProductIdentification, ResaleValuation
from scanner.report import FIELDNAMES as LEGACY_FIELDNAMES


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


class TestLoadLatestLegacyScanPayload(unittest.TestCase):
    """Covers the new data-to-UI transformation this task adds: reading
    the legacy CSV pipeline's already-persisted, already-computed rows
    into a JSON-embeddable shape without recomputing anything."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.legacy_index_path = os.path.join(self.tmpdir.name, "index.json")

    def _write_legacy_csv(self, filename, rows):
        path = os.path.join(self.tmpdir.name, filename)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=LEGACY_FIELDNAMES)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in LEGACY_FIELDNAMES})
        return path

    def test_returns_none_when_no_index_exists(self):
        self.assertIsNone(
            load_latest_legacy_scan_payload(legacy_index_path=self.legacy_index_path, reports_dir=self.tmpdir.name)
        )

    def test_returns_none_when_index_has_no_reports(self):
        with open(self.legacy_index_path, "w", encoding="utf-8") as f:
            json.dump({"count": 0, "reports": []}, f)
        self.assertIsNone(
            load_latest_legacy_scan_payload(legacy_index_path=self.legacy_index_path, reports_dir=self.tmpdir.name)
        )

    def test_returns_none_when_corrupt(self):
        with open(self.legacy_index_path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertIsNone(
            load_latest_legacy_scan_payload(legacy_index_path=self.legacy_index_path, reports_dir=self.tmpdir.name)
        )

    def test_returns_none_when_csv_file_missing_on_disk(self):
        with open(self.legacy_index_path, "w", encoding="utf-8") as f:
            json.dump({"reports": [{"csv": "opportunities_missing.csv", "timestamp": "2026-08-17T08:21", "rows": 1}]}, f)
        self.assertIsNone(
            load_latest_legacy_scan_payload(legacy_index_path=self.legacy_index_path, reports_dir=self.tmpdir.name)
        )

    def test_default_legacy_index_path_is_derived_from_reports_dir_not_the_real_repo(self):
        # Regression guard: legacy_index_path must default relative to the
        # *reports_dir argument*, not a fixed real-repo path -- otherwise a
        # caller that only overrides reports_dir (as every test/tmpdir
        # caller does) would silently read the real repo's reports/index.json.
        self.assertIsNone(load_latest_legacy_scan_payload(reports_dir=self.tmpdir.name))

    def test_reads_newest_csv_and_coerces_numeric_fields_without_recomputation(self):
        self._write_legacy_csv("opportunities_20260817_0821.csv", [
            {
                "category": "Electronics & Tech", "source": "Turners", "data_basis": "Real price + condition",
                "title": "TP-Link Powerline Starter Kit", "url": "https://www.turners.co.nz/x",
                "price_nzd": "1.0", "score": "9", "condition": "As New", "location": "Napier",
                "resale_likelihood": "high", "suggested_resale_price_nzd": "65",
                "potential_profit_nzd": "64", "potential_profit_pct": "6400",
                "notes": "Reserve: Reserve Met; Closes 23 Aug 26",
            },
        ])
        with open(self.legacy_index_path, "w", encoding="utf-8") as f:
            json.dump(
                {"reports": [{"csv": "opportunities_20260817_0821.csv", "timestamp": "2026-08-17T08:21", "rows": 1}]}, f
            )

        payload = load_latest_legacy_scan_payload(legacy_index_path=self.legacy_index_path, reports_dir=self.tmpdir.name)

        self.assertIsNotNone(payload)
        self.assertEqual(payload["run_timestamp"], "2026-08-17T08:21")
        self.assertEqual(payload["row_count"], 1)
        self.assertEqual(payload["csv_filename"], "opportunities_20260817_0821.csv")
        row = payload["rows"][0]
        # Numeric fields coerced to float, matching the value the CSV
        # already held -- never a recalculated number.
        self.assertEqual(row["price_nzd"], 1.0)
        self.assertIsInstance(row["price_nzd"], float)
        self.assertEqual(row["score"], 9.0)
        self.assertEqual(row["potential_profit_nzd"], 64.0)
        self.assertEqual(row["potential_profit_pct"], 6400.0)
        # Non-numeric fields pass through untouched.
        self.assertEqual(row["condition"], "As New")
        self.assertEqual(row["location"], "Napier")
        self.assertEqual(row["notes"], "Reserve: Reserve Met; Closes 23 Aug 26")
        self.assertEqual(row["data_basis"], "Real price + condition")

    def test_blank_numeric_cells_become_none_not_zero(self):
        self._write_legacy_csv("opportunities_20260817_0821.csv", [
            {"category": "Health & Beauty", "source": "Turners", "title": "Item with no price",
             "url": "https://www.turners.co.nz/y", "price_nzd": "", "score": ""},
        ])
        with open(self.legacy_index_path, "w", encoding="utf-8") as f:
            json.dump(
                {"reports": [{"csv": "opportunities_20260817_0821.csv", "timestamp": "2026-08-17T08:21", "rows": 1}]}, f
            )

        payload = load_latest_legacy_scan_payload(legacy_index_path=self.legacy_index_path, reports_dir=self.tmpdir.name)

        row = payload["rows"][0]
        self.assertIsNone(row["price_nzd"])
        self.assertIsNone(row["score"])

    def test_skips_blank_category_separator_rows(self):
        # scanner/report.py's write_report() inserts an all-blank row
        # between categories -- csv.DictReader would otherwise surface it
        # as a fake "opportunity" with every field blank.
        self._write_legacy_csv("opportunities_20260817_0821.csv", [
            {"category": "Electronics & Tech", "source": "Turners", "title": "Real item", "url": "https://www.turners.co.nz/x", "score": "9"},
            {},  # blank separator row, exactly as write_report() writes between categories
            {"category": "House & Garden", "source": "Turners", "title": "Another real item", "url": "https://www.turners.co.nz/z", "score": "5"},
        ])
        with open(self.legacy_index_path, "w", encoding="utf-8") as f:
            json.dump(
                {"reports": [{"csv": "opportunities_20260817_0821.csv", "timestamp": "2026-08-17T08:21", "rows": 3}]}, f
            )

        payload = load_latest_legacy_scan_payload(legacy_index_path=self.legacy_index_path, reports_dir=self.tmpdir.name)

        self.assertEqual(payload["row_count"], 2)
        self.assertEqual([r["title"] for r in payload["rows"]], ["Real item", "Another real item"])

    def test_reads_the_newest_entry_when_multiple_reports_exist(self):
        self._write_legacy_csv("opportunities_older.csv", [
            {"category": "A", "source": "Turners", "title": "Old item", "url": "https://www.turners.co.nz/old", "score": "1"},
        ])
        self._write_legacy_csv("opportunities_newer.csv", [
            {"category": "A", "source": "Turners", "title": "New item", "url": "https://www.turners.co.nz/new", "score": "9"},
        ])
        with open(self.legacy_index_path, "w", encoding="utf-8") as f:
            json.dump({"reports": [
                {"csv": "opportunities_newer.csv", "timestamp": "2026-08-17T08:21", "rows": 1},
                {"csv": "opportunities_older.csv", "timestamp": "2026-08-16T10:56", "rows": 1},
            ]}, f)

        payload = load_latest_legacy_scan_payload(legacy_index_path=self.legacy_index_path, reports_dir=self.tmpdir.name)

        self.assertEqual(payload["rows"][0]["title"], "New item")


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
        self.assertIn("Opportunity dashboard", html)

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

    def test_numeric_filters_no_longer_rerender_filter_bar_on_every_keystroke(self):
        # Regression guard for the filter-focus-loss fix: render() must not
        # call renderFilters(). renderFilters() replaces every filter
        # control's DOM node via innerHTML; since render() runs on every
        # keystroke in the free-text filters (Min price, Max price, Min
        # ROI/profit %, Min confidence %), calling it there used to destroy
        # and recreate the very input the user was typing into, dropping
        # keyboard focus back to <body> and silently swallowing every
        # keystroke after the first (typing "500" only ever registered as
        # "5"). renderFilters() must instead run exactly once, up front, so
        # each control's DOM node -- and the user's focus in it -- persists
        # for the life of the page.
        self._persist_run([_opportunity()], decision_counts={"BUY": 1})
        render_latest_deal_queue(
            index_path=self.index_path, reports_dir=self.tmpdir.name, output_path=self.output_path,
        )
        with open(self.output_path, encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn("function render() {\n    renderFilters();", html)
        self.assertEqual(html.count("renderFilters();"), 1)
        # The numeric filters must still update state and trigger a
        # re-render of the results on every keystroke -- only the filter
        # bar's own DOM must stop being rebuilt.
        for field_id in ("f-min-price", "f-max-price", "f-min-roi", "f-min-confidence"):
            self.assertIn(
                "document.getElementById('%s').addEventListener('input', function () { state." % field_id, html,
            )

    def test_decision_pass_shows_pass_items_without_show_passed_toggle(self):
        # Regression guard: selecting Decision = PASS must be a
        # self-sufficient way to see PASS opportunities. It previously
        # required the user to also discover and enable the separate
        # "Show passed" control, since passFilters() suppressed every PASS
        # item unconditionally whenever showPass was off -- producing "No
        # opportunities match the current filters." even though PASS items
        # existed. "Show passed" must still control PASS visibility in
        # mixed views (All/other-decision).
        self._persist_run(
            [_opportunity(decision="BUY"), _opportunity(decision="PASS", url="https://www.turners.co.nz/y")],
            decision_counts={"BUY": 1, "PASS": 1},
        )
        render_latest_deal_queue(
            index_path=self.index_path, reports_dir=self.tmpdir.name, output_path=self.output_path,
        )
        with open(self.output_path, encoding="utf-8") as f:
            html = f.read()
        self.assertIn(
            "if (!state.showPass && state.decision !== 'PASS' && sortTier(it) === TIER.PASS) return false;", html,
        )


class TestRenderLatestDealQueueWithLegacyData(unittest.TestCase):
    """The combined-dashboard behaviour this task adds: both pipelines'
    latest persisted output get embedded into the same page, independently,
    with neither one blocking the other."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.index_path = os.path.join(self.tmpdir.name, "discovery_index.json")
        self.legacy_index_path = os.path.join(self.tmpdir.name, "index.json")
        self.output_path = os.path.join(self.tmpdir.name, "deal_queue.html")

    def _persist_discovery_run(self, opportunities, **meta_overrides):
        meta = {
            "run_timestamp": "2026-08-17T08:24:00+00:00", "mode": "discover", "queries_run": 15,
            "candidates_found": 5, "candidates_verified": 3, "candidates_verification_dropped": 2,
            "opportunity_count": len(opportunities), "decision_counts": {},
        }
        meta.update(meta_overrides)
        path, payload = write_discovery_report(opportunities, meta, reports_dir=self.tmpdir.name)
        update_discovery_index(path, payload, index_path=self.index_path)
        return payload

    def _persist_legacy_run(self, rows, csv_filename="opportunities_20260817_0821.csv", timestamp="2026-08-17T08:21"):
        path = os.path.join(self.tmpdir.name, csv_filename)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=LEGACY_FIELDNAMES)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in LEGACY_FIELDNAMES})
        with open(self.legacy_index_path, "w", encoding="utf-8") as f:
            json.dump({"reports": [{"csv": csv_filename, "timestamp": timestamp, "rows": len(rows)}]}, f)

    def _extract_script_json(self, html, element_id):
        start_marker = f'<script id="{element_id}" type="application/json">'
        end_marker = "</script>"
        start = html.index(start_marker) + len(start_marker)
        end = html.index(end_marker, start)
        return json.loads(html[start:end])

    def test_returns_none_when_neither_pipeline_has_run(self):
        result = render_latest_deal_queue(
            index_path=self.index_path, legacy_index_path=self.legacy_index_path,
            reports_dir=self.tmpdir.name, output_path=self.output_path,
        )
        self.assertIsNone(result)

    def test_renders_when_only_legacy_data_exists(self):
        self._persist_legacy_run([
            {"category": "Electronics & Tech", "source": "Turners", "data_basis": "Real price + condition",
             "title": "Hikvision Security Camera", "url": "https://www.turners.co.nz/cam",
             "price_nzd": "2.0", "score": "9", "condition": "As New", "location": "Napier"},
        ])
        result = render_latest_deal_queue(
            index_path=self.index_path, legacy_index_path=self.legacy_index_path,
            reports_dir=self.tmpdir.name, output_path=self.output_path,
        )
        self.assertEqual(result, self.output_path)
        with open(self.output_path, encoding="utf-8") as f:
            html = f.read()

        discovery_embedded = self._extract_script_json(html, "discovery-report-data")
        legacy_embedded = self._extract_script_json(html, "legacy-scan-data")
        self.assertIsNone(discovery_embedded)
        self.assertEqual(legacy_embedded["row_count"], 1)
        self.assertEqual(legacy_embedded["rows"][0]["title"], "Hikvision Security Camera")
        self.assertEqual(legacy_embedded["rows"][0]["price_nzd"], 2.0)

    def test_renders_when_both_pipelines_have_data(self):
        self._persist_discovery_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        self._persist_legacy_run([
            {"category": "House & Garden", "source": "Turners", "title": "Tinned Security Cable",
             "url": "https://www.turners.co.nz/cable", "price_nzd": "2.0", "score": "9"},
        ])
        result = render_latest_deal_queue(
            index_path=self.index_path, legacy_index_path=self.legacy_index_path,
            reports_dir=self.tmpdir.name, output_path=self.output_path,
        )
        self.assertEqual(result, self.output_path)
        with open(self.output_path, encoding="utf-8") as f:
            html = f.read()

        discovery_embedded = self._extract_script_json(html, "discovery-report-data")
        legacy_embedded = self._extract_script_json(html, "legacy-scan-data")
        self.assertEqual(discovery_embedded["opportunities"][0]["decision"], "BUY")
        self.assertEqual(legacy_embedded["rows"][0]["title"], "Tinned Security Cable")

    def test_legacy_default_index_path_derives_from_reports_dir(self):
        # render_latest_deal_queue() called the way main.py calls it (no
        # legacy_index_path override) must still find <reports_dir>/index.json,
        # not a fixed real-repo path, when reports_dir is overridden.
        self._persist_legacy_run([
            {"category": "A", "source": "Turners", "title": "Item", "url": "https://www.turners.co.nz/x", "score": "5"},
        ])
        result = render_latest_deal_queue(
            index_path=self.index_path, reports_dir=self.tmpdir.name, output_path=self.output_path,
        )
        self.assertEqual(result, self.output_path)
        with open(self.output_path, encoding="utf-8") as f:
            html = f.read()
        legacy_embedded = self._extract_script_json(html, "legacy-scan-data")
        self.assertEqual(legacy_embedded["rows"][0]["title"], "Item")


if __name__ == "__main__":
    unittest.main()
