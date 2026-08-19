import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import csv
import json
import tempfile
import unittest

from scanner.deal_queue_report import (
    DEFAULT_OUTPUT_PATH,
    load_bankroll_config,
    load_hunting_payload,
    load_latest_discovery_payload,
    load_latest_legacy_scan_payload,
    render_latest_deal_queue,
)
from scanner.discovery_report import write_discovery_report, update_discovery_index
from scanner.hunting_store import save_hunting_state, star
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


class TestLoadBankrollConfig(unittest.TestCase):
    """Covers the Command Centre's one new data source: config.json's
    static bankroll reference figures. Must stay read-only and must never
    fabricate a value when the real numbers aren't there."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.config_path = os.path.join(self.tmpdir.name, "config.json")

    def _write_config(self, data):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_returns_none_when_file_missing(self):
        self.assertIsNone(load_bankroll_config(config_path=self.config_path))

    def test_returns_none_when_corrupt(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertIsNone(load_bankroll_config(config_path=self.config_path))

    def test_returns_none_when_no_bankroll_key(self):
        self._write_config({"sites": {"thorntons": True}})
        self.assertIsNone(load_bankroll_config(config_path=self.config_path))

    def test_returns_starting_and_target_when_present(self):
        self._write_config({"bankroll": {
            "starting_bankroll": 500, "target_bankroll": 10000,
            "minimum_profit": 10, "minimum_roi_percent": 40,
        }})
        result = load_bankroll_config(config_path=self.config_path)
        self.assertEqual(result, {"starting_bankroll": 500, "target_bankroll": 10000})

    def test_never_exposes_fields_this_codebase_does_not_track(self):
        # Regression guard: available_cash/inventory_value/realised_profit
        # must never appear in the returned dict, even if some future
        # config.json edit adds them under "bankroll" -- nothing in the
        # codebase computes/persists those yet (see PROJECT_STATE.md), so
        # surfacing them here would be inventing a number.
        self._write_config({"bankroll": {
            "starting_bankroll": 500, "target_bankroll": 10000,
            "available_cash": 999, "inventory_value": 111, "realised_profit": 222,
        }})
        result = load_bankroll_config(config_path=self.config_path)
        self.assertEqual(set(result.keys()), {"starting_bankroll", "target_bankroll"})


class TestRenderLatestDealQueueBankroll(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.index_path = os.path.join(self.tmpdir.name, "discovery_index.json")
        self.output_path = os.path.join(self.tmpdir.name, "deal_queue.html")

    def _persist_run(self, opportunities, **meta_overrides):
        meta = {
            "run_timestamp": "2026-08-19T09:00:00+00:00", "mode": "discover", "queries_run": 15,
            "candidates_found": 5, "candidates_verified": 3, "candidates_verification_dropped": 2,
            "opportunity_count": len(opportunities), "decision_counts": {},
        }
        meta.update(meta_overrides)
        path, payload = write_discovery_report(opportunities, meta, reports_dir=self.tmpdir.name)
        update_discovery_index(path, payload, index_path=self.index_path)
        return payload

    def _extract_script_json(self, html, element_id):
        start_marker = f'<script id="{element_id}" type="application/json">'
        end_marker = "</script>"
        start = html.index(start_marker) + len(start_marker)
        end = html.index(end_marker, start)
        return json.loads(html[start:end])

    def test_bankroll_embedded_when_config_path_given(self):
        self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        config_path = os.path.join(self.tmpdir.name, "config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump({"bankroll": {"starting_bankroll": 500, "target_bankroll": 10000}}, f)

        render_latest_deal_queue(
            index_path=self.index_path, reports_dir=self.tmpdir.name,
            output_path=self.output_path, config_path=config_path,
        )
        with open(self.output_path, encoding="utf-8") as f:
            html = f.read()
        bankroll_embedded = self._extract_script_json(html, "bankroll-data")
        self.assertEqual(bankroll_embedded, {"starting_bankroll": 500, "target_bankroll": 10000})

    def test_default_config_path_does_not_leak_real_repo_config(self):
        # Regression guard mirroring the existing legacy_index_path
        # protection: when the caller only overrides reports_dir (as
        # main.py effectively does via the real reports/ directory, and
        # as every isolated test here does), the bankroll default must be
        # derived from that reports_dir, not fall back to a fixed
        # real-repo config.json path.
        self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        render_latest_deal_queue(
            index_path=self.index_path, reports_dir=self.tmpdir.name, output_path=self.output_path,
        )
        with open(self.output_path, encoding="utf-8") as f:
            html = f.read()
        bankroll_embedded = self._extract_script_json(html, "bankroll-data")
        self.assertIsNone(bankroll_embedded)


class TestCommandCentreMarkup(unittest.TestCase):
    """Covers the new Command Centre presentation layer added on top of
    the existing Deal Queue. These are static-HTML/JS-source regression
    guards (matching this file's existing style) rather than a headless
    browser run -- they lock in that the required structural pieces and
    architectural guardrails stay in the generated source."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.index_path = os.path.join(self.tmpdir.name, "discovery_index.json")
        self.output_path = os.path.join(self.tmpdir.name, "deal_queue.html")

    def _persist_run(self, opportunities, **meta_overrides):
        meta = {
            "run_timestamp": "2026-08-19T09:00:00+00:00", "mode": "discover", "queries_run": 15,
            "candidates_found": 5, "candidates_verified": 3, "candidates_verification_dropped": 2,
            "opportunity_count": len(opportunities), "decision_counts": {},
        }
        meta.update(meta_overrides)
        path, payload = write_discovery_report(opportunities, meta, reports_dir=self.tmpdir.name)
        update_discovery_index(path, payload, index_path=self.index_path)
        return payload

    def _render(self):
        render_latest_deal_queue(
            index_path=self.index_path, reports_dir=self.tmpdir.name, output_path=self.output_path,
        )
        with open(self.output_path, encoding="utf-8") as f:
            return f.read()

    def test_command_centre_header_and_sections_present(self):
        self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        html = self._render()
        self.assertIn("Hello Rhys", html)
        self.assertIn('id="metrics-row"', html)
        self.assertIn('id="top-grid"', html)
        self.assertIn('id="browse-grid"', html)
        self.assertIn('id="all-opportunities-heading"', html)

    def test_top_opportunities_reuse_existing_tier_ranking_not_a_new_model(self):
        # Architectural rule: the Command Centre must not introduce a
        # second valuation/scoring/confidence model. Top opportunities
        # must be computed from the same sortTier/nativeScoreForSort the
        # original list already used.
        self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        html = self._render()
        self.assertIn("function byTierThenScore(a, b) {", html)
        self.assertIn("var ta = sortTier(a), tb = sortTier(b);", html)
        self.assertIn("return nativeScoreForSort(b) - nativeScoreForSort(a);", html)
        self.assertIn("function computeTopPicks() {", html)

    def test_top_opportunities_does_not_pad_with_legacy_items_to_fill_the_panel(self):
        # Curation rule from the visual QA pass: BUY/CAPITAL RISK/verified
        # WATCH items are decision-graded and are never capped away, but
        # daily-scan (legacy) items -- a plain 1-10 score with no
        # BUY/WATCH gate behind it -- must never be used as filler just to
        # reach a round panel size. At most LEGACY_TOP_FILL_CAP (3) of the
        # strongest ones are added for context, only after every
        # decision-graded item is already included, and only if that still
        # leaves room.
        self._persist_run([_opportunity(decision="WATCH", url="https://www.turners.co.nz/w1")], decision_counts={"WATCH": 1})
        html = self._render()
        self.assertIn("var LEGACY_TOP_FILL_CAP = 3;", html)
        self.assertIn(
            "var legacyFillCount = Math.min(LEGACY_TOP_FILL_CAP, Math.max(0, MAX_TOP_PICKS - picks.length), legacyRanked.length);",
            html,
        )
        # The explanatory caption element must exist so a user can see
        # *why* the panel stopped short instead of assuming items are
        # missing -- and it must say nothing is hidden.
        self.assertIn('id="top-cap-note"', html)
        self.assertIn("Nothing is hidden: the rest are in All opportunities below.", html)

    def test_no_buy_banner_logic_present(self):
        # Requirement: if there are no BUY opportunities, say so explicitly
        # rather than presenting WATCH items as if they were buys.
        self._persist_run([_opportunity(decision="WATCH")], decision_counts={"WATCH": 1})
        html = self._render()
        self.assertIn("No BUY-tier opportunities right now", html)
        self.assertIn("if (buyCount === 0) {", html)

    def test_sort_control_reuses_existing_persisted_fields(self):
        self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        html = self._render()
        # The sort <select> and its options are built client-side at
        # runtime (like every other filter control), so the static file
        # contains the JS source that constructs it, not the rendered
        # <select> markup itself.
        self.assertIn("selectHtml('f-sort',", html)
        self.assertIn("document.getElementById('f-sort').addEventListener('change',", html)
        # profitForSort/roiForFilter/confidence read only fields the
        # payload already contains -- no new field is invented for sorting.
        self.assertIn("function profitForSort(it) {", html)
        self.assertIn("it.raw.expected_net_profit_low", html)
        self.assertIn("it.raw.potential_profit_nzd", html)

    def test_asking_and_max_buy_labelled_distinctly_and_target_offer_not_invented(self):
        self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        html = self._render()
        self.assertIn('<span class="price-label">Asking</span>', html)
        self.assertIn('<span class="price-label">Max buy</span>', html)
        # No fabricated "Target offer" field/value anywhere -- the schema
        # has no authoritative target-offer figure today.
        self.assertNotIn("Target offer", html)

    def test_zero_opportunity_run_still_renders_command_centre_sections(self):
        self._persist_run([], decision_counts={})
        html = self._render()
        self.assertIn('id="metrics-row"', html)
        self.assertIn('id="top-grid"', html)
        self.assertIn('id="browse-grid"', html)

    def test_metric_tiles_use_dedicated_classes_not_shared_pill_badges(self):
        # Regression guard for the visual-QA bug: metric tiles must not
        # reuse .pill-buy/.pill-watch/.pill-pass/.pill-legacy (those carry
        # a background-color rule for the small rounded status badges
        # elsewhere on the page; reusing the class name leaked that
        # background onto the tiles as an unintended colored band).
        self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        html = self._render()
        self.assertIn("metricTile('BUY', buy, 'metric-value-buy')", html)
        self.assertIn("metricTile('WATCH', watch, 'metric-value-watch'", html)
        self.assertIn("metricTile('PASS', pass, 'metric-value-pass')", html)
        self.assertIn("metricTile('DAILY SCAN ITEMS', legacyRows.length, 'metric-value-legacy'", html)
        self.assertNotIn("metricTile('BUY', buy, 'pill-buy')", html)
        self.assertNotIn(".metric-value.pill-buy", html)
        # Grid layout (not flex) so tiles in the same row are guaranteed
        # equal height regardless of how long each tile's note text is.
        self.assertIn(".metrics-row { display: grid;", html)

    def test_header_no_longer_duplicates_decision_counts(self):
        # Regression guard: the dark header must only show run-freshness
        # info now -- the BUY/WATCH/PASS/etc counts live in exactly one
        # place (the metric tiles), not repeated in the header too.
        self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        html = self._render()
        self.assertIn("Discovery updated <b>", html)
        self.assertIn("Daily scan updated <b>", html)
        self.assertNotIn("' opportunities &middot; ' + counts", html)
        self.assertNotIn("unverified-source WATCH (unpriced)", html)

    def test_confidence_chip_present_for_discovery_only_and_no_placeholder(self):
        # Requirement: confidence must be glanceable on the card face when
        # authoritative (Discovery items only), and must render nothing --
        # not a "Not available" placeholder -- when it isn't.
        self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        html = self._render()
        self.assertIn("function confidenceGlance(it) {", html)
        self.assertIn("if (isUnsupported(it)) return '';", html)
        self.assertIn("if (c === null || c === undefined || c === '') return '';", html)
        self.assertIn("return '<span class=\"confidence-chip\">' + Math.round(n) + '% confidence</span>';", html)
        # Wired in next to the native score on every row, discovery or legacy.
        self.assertIn("'<span class=\"score\">' + nativeScoreLine(it) + '</span>' +\n      confidenceGlance(it) +", html)
        # confidence() itself already returns null for legacy items
        # (no confidence field in that schema at all) -- confidenceGlance
        # relies on that rather than adding a second "is legacy" check.
        self.assertIn("function confidence(it) {\n    if (it.pipeline === 'discovery') return (it.raw.valuation || {}).confidence_pct;\n    return null;\n  }", html)

    def test_confidence_gated_on_verification_not_just_on_a_number_present(self):
        # Regression guard found during visual QA: an unverified-source
        # item's confidence_pct is just ResaleValuation's 0.0 dataclass
        # default (valuation is never attempted for these -- see
        # scanner.models.Opportunity.verification_status) -- not a real
        # assessment. Showing "0% confidence" there would misrepresent
        # "never checked" as "checked and it's worthless", so the chip
        # must be gated on verification status, not merely on whether
        # confidence_pct is non-null.
        o = _opportunity(decision="WATCH")
        o.verification_status = "unsupported"
        o.valuation.confidence_pct = 0.0
        self._persist_run([o], decision_counts={"WATCH": 1})
        html = self._render()
        self.assertIn("if (isUnsupported(it)) return '';", html)


class TestLoadHuntingPayload(unittest.TestCase):
    def test_missing_file_returns_empty_but_well_formed_payload(self):
        # Unlike the discovery/legacy loaders, a missing hunting-state file
        # is not "no run has happened" -- it's just "nothing hunted yet" --
        # so this must never return None.
        payload = load_hunting_payload(hunting_state_path="/tmp/definitely_missing_hunting_xyz.json")
        self.assertEqual(payload, {"hunting": {}})

    def test_reads_persisted_state_verbatim(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "hunting_state.json")
            state = {}
            star(state, "Turners", "https://example.com/x", notes="watching")
            save_hunting_state(state, path)

            payload = load_hunting_payload(hunting_state_path=path)
            self.assertEqual(payload, {"hunting": state})


class TestRenderLatestDealQueueWithHuntingState(unittest.TestCase):
    """The Hunting persistence slice: a third, independent payload embedded
    alongside discovery/legacy, without mutating either of them."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.index_path = os.path.join(self.tmpdir.name, "discovery_index.json")
        self.output_path = os.path.join(self.tmpdir.name, "deal_queue.html")
        self.hunting_state_path = os.path.join(self.tmpdir.name, "hunting_state.json")

    def _persist_run(self, opportunities, **meta_overrides):
        meta = {
            "run_timestamp": "2026-08-19T09:00:00+00:00", "mode": "discover", "queries_run": 5,
            "candidates_found": 1, "candidates_verified": 1, "candidates_verification_dropped": 0,
            "opportunity_count": len(opportunities), "decision_counts": {},
        }
        meta.update(meta_overrides)
        path, payload = write_discovery_report(opportunities, meta, reports_dir=self.tmpdir.name)
        update_discovery_index(path, payload, index_path=self.index_path)
        return payload

    def _render(self):
        render_latest_deal_queue(
            index_path=self.index_path, reports_dir=self.tmpdir.name, output_path=self.output_path,
            hunting_state_path=self.hunting_state_path,
        )
        with open(self.output_path, encoding="utf-8") as f:
            return f.read()

    def _embedded_json(self, html, element_id):
        start_marker = '<script id="%s" type="application/json">' % element_id
        end_marker = "</script>"
        start = html.index(start_marker) + len(start_marker)
        end = html.index(end_marker, start)
        return json.loads(html[start:end])

    def test_renders_empty_hunting_snapshot_when_no_state_file_exists(self):
        self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        html = self._render()
        embedded = self._embedded_json(html, "hunting-state-data")
        self.assertEqual(embedded, {"hunting": {}})

    def test_embeds_persisted_hunting_state_verbatim(self):
        self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        state = {}
        star(state, "Turners", "https://www.turners.co.nz/x", notes="check condition", target_offer_override=75.0)
        save_hunting_state(state, self.hunting_state_path)

        html = self._render()
        embedded = self._embedded_json(html, "hunting-state-data")
        self.assertEqual(embedded, {"hunting": state})
        entry = list(embedded["hunting"].values())[0]
        self.assertEqual(entry["status"], "hunting")
        self.assertEqual(entry["notes"], "check condition")
        self.assertEqual(entry["target_offer_override"], 75.0)

    def test_discovery_payload_embedding_is_not_mutated_by_hunting_state(self):
        # Regression guard for the separation-of-concerns requirement:
        # loading/embedding Hunting state alongside the discovery payload
        # must not add, remove, or alter any field on the discovery
        # opportunities themselves.
        payload = self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        state = {}
        star(state, "Turners", "https://www.turners.co.nz/x")
        save_hunting_state(state, self.hunting_state_path)

        html = self._render()
        embedded_discovery = self._embedded_json(html, "discovery-report-data")
        self.assertEqual(embedded_discovery, payload)
        self.assertNotIn("_hunting_key", json.dumps(embedded_discovery))
        self.assertNotIn("hunting", embedded_discovery["opportunities"][0])

    def test_default_hunting_state_path_is_derived_at_call_time_not_import_time(self):
        # Mirrors the existing legacy_index_path/config_path pattern: a
        # caller/test that only overrides reports_dir/output_path must not
        # silently fall back to reading the real repo's
        # data/hunting_state.json.
        self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        render_latest_deal_queue(
            index_path=self.index_path, reports_dir=self.tmpdir.name, output_path=self.output_path,
        )
        with open(self.output_path, encoding="utf-8") as f:
            html = f.read()
        embedded = self._embedded_json(html, "hunting-state-data")
        # Whatever the real repo's data/hunting_state.json happens to
        # contain is irrelevant here -- this just proves the call didn't
        # raise and produced a well-formed (if unrelated) payload.
        self.assertIn("hunting", embedded)

    def test_html_includes_star_control_and_hunting_filter(self):
        self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        html = self._render()
        self.assertIn("star-btn", html)
        self.assertIn("toggleHunting(it)", html)
        self.assertIn('id="toggle-hunting"', html)
        self.assertIn("state.huntingOnly", html)

    def test_html_distinguishes_scanner_max_buy_from_target_offer(self):
        self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        html = self._render()
        self.assertIn("Scanner max buy", html)
        self.assertIn("Your target offer", html)
        self.assertIn("it.raw.max_buy_price", html.split("function renderHuntingSection")[1][:1500])

    def test_html_upgrades_to_live_state_via_fetch(self):
        self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        html = self._render()
        self.assertIn("fetch('/api/hunting'", html)
        self.assertIn("liveMode = true;", html)


class TestRunScanMarkup(unittest.TestCase):
    """Command Centre "Run Scan" control + live-progress panel. Like
    TestCommandCentreMarkup above, these are static-HTML/JS-source
    regression guards, not a headless browser run -- see
    tests/test_scan_progress.py and tests/test_dashboard_server.py for the
    actual progress-telemetry and endpoint behaviour these markup pieces
    talk to.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.index_path = os.path.join(self.tmpdir.name, "discovery_index.json")
        self.output_path = os.path.join(self.tmpdir.name, "deal_queue.html")

    def _persist_run(self, opportunities, **meta_overrides):
        meta = {
            "run_timestamp": "2026-08-19T09:00:00+00:00", "mode": "discover", "queries_run": 15,
            "candidates_found": 5, "candidates_verified": 3, "candidates_verification_dropped": 2,
            "opportunity_count": len(opportunities), "decision_counts": {},
        }
        meta.update(meta_overrides)
        path, payload = write_discovery_report(opportunities, meta, reports_dir=self.tmpdir.name)
        update_discovery_index(path, payload, index_path=self.index_path)
        return payload

    def _render(self, hunting_state_path=None):
        render_latest_deal_queue(
            index_path=self.index_path, reports_dir=self.tmpdir.name, output_path=self.output_path,
            **({"hunting_state_path": hunting_state_path} if hunting_state_path else {}),
        )
        with open(self.output_path, encoding="utf-8") as f:
            return f.read()

    def test_run_scan_button_and_status_panel_present(self):
        self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        html = self._render()
        self.assertIn('id="scan-run-btn"', html)
        self.assertIn("RUN SCAN", html)
        self.assertIn('id="scan-status"', html)

    def test_polls_scan_status_endpoint_not_faster_than_once_a_second(self):
        self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        html = self._render()
        self.assertIn("fetch('/api/scan/status'", html)
        self.assertIn("POST", html)  # sanity: POST is used somewhere (scan/start)
        self.assertIn("/api/scan/start", html)
        self.assertIn("var SCAN_POLL_MS = 1000;", html)

    def test_no_overall_percentage_is_ever_rendered(self):
        # Explicit product requirement: stage checklist + real item counts
        # only, never a fabricated overall percentage bar.
        self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        html = self._render()
        scan_js = html.split("Run Scan: on-demand discovery scan")[1]
        self.assertNotIn("%'", scan_js[:6000])
        self.assertNotIn("progress-bar", scan_js[:6000])

    def test_stage_status_glyphs_reflect_real_backend_field_not_invented(self):
        self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        html = self._render()
        self.assertIn("data.stage_status", html)
        self.assertIn("data.queries_completed", html)
        self.assertIn("data.research_completed", html)
        self.assertIn("data.decision_counts", html)

    def test_completion_reloads_the_page_to_pick_up_regenerated_data(self):
        self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        html = self._render()
        self.assertIn("window.location.reload()", html)

    def test_scan_panel_does_not_mutate_discovery_payload_embedding(self):
        # Regression guard mirroring
        # test_discovery_payload_embedding_is_not_mutated_by_hunting_state
        # in TestRenderLatestDealQueueWithHuntingState -- adding the Run
        # Scan button/panel/script must not touch how the discovery
        # payload is embedded.
        payload = self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        html = self._render()
        start_marker = '<script id="discovery-report-data" type="application/json">'
        end_marker = "</script>"
        start = html.index(start_marker) + len(start_marker)
        end = html.index(end_marker, start)
        embedded_discovery = json.loads(html[start:end])
        self.assertEqual(embedded_discovery, payload)

    def test_scan_panel_does_not_mutate_hunting_payload_embedding(self):
        state = {}
        star(state, "Turners", "https://www.turners.co.nz/x")
        hunting_path = os.path.join(self.tmpdir.name, "hunting_state.json")
        save_hunting_state(state, hunting_path)
        self._persist_run([_opportunity(decision="BUY")], decision_counts={"BUY": 1})
        html = self._render(hunting_state_path=hunting_path)
        start_marker = '<script id="hunting-state-data" type="application/json">'
        end_marker = "</script>"
        start = html.index(start_marker) + len(start_marker)
        end = html.index(end_marker, start)
        embedded_hunting = json.loads(html[start:end])
        self.assertEqual(embedded_hunting, {"hunting": state})


if __name__ == "__main__":
    unittest.main()
