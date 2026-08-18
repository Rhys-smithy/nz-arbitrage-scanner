"""Phase 4B.3 (+ 4B.8 Opportunity Dashboard): a static HTML view over the
persisted Opportunity results from BOTH scanner pipelines.

This module does not compute, sort, filter, or reinterpret business logic
(valuation, scoring, decisions, thresholds, currency, similarity). It
loads each pipeline's already-persisted output verbatim and embeds it
into a self-contained HTML file:

- Discovery (Phase 3, ``python main.py --mode discover``): the full
  ``scanner.models.Opportunity`` records via
  ``scanner/discovery_report.py`` -> ``reports/discovery_index.json``.
- Legacy scan (Phase 2, ``python main.py`` default): the older row-dict
  CSV pipeline via ``scanner/report.py`` -> ``reports/index.json``. This
  pipeline was deliberately never merged into the discovery schema (see
  ``scanner/discovery_report.py``'s docstring) -- it uses a different,
  simpler shape (no decision/flip_score/confidence/liquidity/ROI-range/
  comparable-evidence). This module respects that separation: it loads
  both payloads independently and renders them side by side, tagged by
  pipeline, rather than forcing them into one fake unified schema.

Every number, label, and grouping the page displays is produced
client-side, in JavaScript, by reading straight from the embedded
payloads -- there is no second schema and no Python-side transformation
of Opportunity data beyond (a) locating the latest run of each pipeline
and (b) converting the legacy CSV's known-numeric text columns to
numbers/None so the UI can treat them the same way it treats discovery's
numbers. Neither step recomputes or reinterprets any value.

The page is a single static file with inline CSS/JS (no build step, no
new dependency, no server) so it opens directly via file:// -- consistent
with how reports/opportunities_*.csv|xlsx already work today.
"""
from __future__ import annotations

import csv
import json
import os
from typing import Optional

from scanner.discovery_report import DEFAULT_INDEX_PATH, REPORTS_DIR

DEFAULT_OUTPUT_PATH = os.path.join(REPORTS_DIR, "deal_queue.html")

# reports/index.json -- the manifest main.py/scanner/report.py already
# maintain for the legacy scan pipeline's CSV/XLSX reports. Unrelated to
# discovery_index.json (different pipeline, different schema).
LEGACY_INDEX_PATH = os.path.join(REPORTS_DIR, "index.json")

# The subset of scanner/report.py's FIELDNAMES that are numeric in
# spirit but arrive from csv.DictReader as plain strings (or "" for
# blank cells, including the blank category-separator rows write_report()
# inserts between categories).
_LEGACY_NUMERIC_FIELDS = (
    "price_nzd",
    "buy_now_price_nzd",
    "score",
    "estimated_new_price_nzd",
    "value_vs_new_pct",
    "suggested_resale_price_nzd",
    "potential_profit_nzd",
    "potential_profit_pct",
)


def load_latest_discovery_payload(
    index_path: str = DEFAULT_INDEX_PATH, reports_dir: str = REPORTS_DIR
) -> Optional[dict]:
    """Reads reports/discovery_index.json, resolves its newest entry, and
    returns that run's full payload dict exactly as
    scanner/discovery_report.py wrote it. Returns None (not a fabricated
    empty payload) if no discovery run has ever completed yet, or if the
    index/latest file can't be read -- callers must treat that as "nothing
    to render", not as a zero-opportunity run."""
    if not os.path.exists(index_path):
        return None
    try:
        with open(index_path, encoding="utf-8") as f:
            index = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    reports = index.get("reports") or []
    if not reports:
        return None

    latest_filename = reports[0].get("json")
    if not latest_filename:
        return None

    latest_path = os.path.join(reports_dir, latest_filename)
    if not os.path.exists(latest_path):
        return None
    try:
        with open(latest_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _coerce_legacy_row(row: dict) -> dict:
    """Converts the known-numeric CSV columns from string to float/None so
    client-side JS can sort/filter/format them numerically, exactly like
    the discovery JSON's numbers already are. Every other field (title,
    url, category, source, condition, location, reasons, explanation,
    notes, search-link URLs, data_basis, resale_likelihood, ...) is left
    exactly as scanner/report.py wrote it -- no reinterpretation, no new
    values, nothing invented."""
    out = dict(row)
    for key in _LEGACY_NUMERIC_FIELDS:
        raw = out.get(key)
        if raw is None or raw == "":
            out[key] = None
        else:
            try:
                out[key] = float(raw)
            except (TypeError, ValueError):
                out[key] = None
    return out


def load_latest_legacy_scan_payload(
    legacy_index_path: Optional[str] = None, reports_dir: str = REPORTS_DIR
) -> Optional[dict]:
    """Reads reports/index.json (the legacy Turners/Thorntons/Mainland
    scan pipeline's manifest), resolves its newest entry, and reads that
    run's CSV verbatim via csv.DictReader.

    This performs no scoring/valuation/decision logic of its own -- every
    value returned was already computed by main.py/scanner/report.py. The
    only transformations are (1) skipping the blank category-separator
    rows write_report() inserts between categories (identified by an
    empty "title", since every real row has one) and (2) the numeric
    coercion in _coerce_legacy_row().

    `legacy_index_path` defaults to `<reports_dir>/index.json` (computed
    at call time, not import time) so callers/tests that override
    `reports_dir` alone still get an isolated default path instead of
    silently falling back to the real repo's reports/index.json.

    Returns None (not a fabricated empty payload) if no legacy scan has
    ever completed, or the index/CSV can't be read -- callers must treat
    that as "nothing to render for this pipeline", not a zero-row run.
    """
    if legacy_index_path is None:
        legacy_index_path = os.path.join(reports_dir, "index.json")

    if not os.path.exists(legacy_index_path):
        return None
    try:
        with open(legacy_index_path, encoding="utf-8") as f:
            index = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    reports = index.get("reports") or []
    if not reports:
        return None

    latest = reports[0]
    csv_filename = latest.get("csv")
    if not csv_filename:
        return None

    csv_path = os.path.join(reports_dir, csv_filename)
    if not os.path.exists(csv_path):
        return None

    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [
                _coerce_legacy_row(row)
                for row in reader
                if (row.get("title") or "").strip()
            ]
    except OSError:
        return None

    return {
        "run_timestamp": latest.get("timestamp"),
        "row_count": len(rows),
        "csv_filename": csv_filename,
        "rows": rows,
    }


def render_latest_deal_queue(
    index_path: str = DEFAULT_INDEX_PATH,
    legacy_index_path: Optional[str] = None,
    reports_dir: str = REPORTS_DIR,
    output_path: str = DEFAULT_OUTPUT_PATH,
) -> Optional[str]:
    """Loads the latest persisted discovery payload AND the latest
    persisted legacy-scan payload -- independently; neither pipeline's
    data is merged, recomputed, or reinterpreted -- and writes both into
    reports/deal_queue.html (a fixed filename, overwritten every run, so
    there's always one current view to open -- the timestamped JSON/CSV
    files remain the historical record).

    Returns the path written, or None only if NEITHER pipeline has ever
    produced a persisted run (nothing to show at all)."""
    discovery_payload = load_latest_discovery_payload(index_path=index_path, reports_dir=reports_dir)
    legacy_payload = load_latest_legacy_scan_payload(legacy_index_path=legacy_index_path, reports_dir=reports_dir)
    if discovery_payload is None and legacy_payload is None:
        return None

    html = _render_html(discovery_payload, legacy_payload)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


def _embed(payload: Optional[dict]) -> str:
    # json.dumps() does not escape "/", so a title/url/etc containing the
    # literal text "</script>" would otherwise close this embedding tag
    # early -- HTML's script-content parsing is text-based, not JSON-aware.
    # Escaping the slash keeps the JSON value identical (JSON treats "\/"
    # and "/" as equivalent) while making it impossible for embedded data
    # to terminate the tag prematurely. `null` (not omitted) when a
    # pipeline has no run yet, so the client JS always has a well-defined
    # value to check.
    return json.dumps(payload).replace("</", "<\\/")


def _render_html(discovery_payload: Optional[dict], legacy_payload: Optional[dict] = None) -> str:
    return (
        _HTML_HEAD
        + _HTML_STYLE
        + _HTML_BODY_START
        + _embed(discovery_payload)
        + _HTML_MID
        + _embed(legacy_payload)
        + _HTML_BODY_END
        + _HTML_SCRIPT
        + _HTML_FOOT
    )


_HTML_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Opportunity dashboard</title>
"""

_HTML_STYLE = """<style>
:root {
  --bg: #f4f5f7; --card: #ffffff; --border: #e2e5ea; --text: #1a2230; --muted: #64748b; --mutedest: #94a3b8;
  --buy: #16a34a; --buy-bg: #e7f7ee; --watch: #b45309; --watch-bg: #fef3e2;
  --risk: #6d28d9; --risk-bg: #efe9fb; --pass: #6b7280; --pass-bg: #eef0f3;
  --unsupported: #9d174d; --unsupported-bg: #fce7f0;
  --accent: #2563eb; --warn: #b45309; --warn-bg: #fef3e2;
  --legacy: #0e7490; --legacy-bg: #e5f6fa;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
a { color: var(--accent); }
header.topbar { background: #16202c; color: #fff; padding: 14px 22px; }
header.topbar .brand { font-weight: 700; letter-spacing: .03em; margin-bottom: 4px; }
header.topbar .status { color: #cbd5e1; font-size: 12.5px; }
header.topbar .status b { color: #fff; font-weight: 600; }
header.topbar .status-row { margin-top: 2px; }
main { max-width: 1080px; margin: 0 auto; padding: 16px 16px 60px; }
.filters { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; margin-bottom: 12px; display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.filters .field { display: flex; flex-direction: column; gap: 3px; font-size: 11px; color: var(--muted); }
.filters select, .filters input[type=number] { font-size: 12.5px; padding: 5px 7px; border: 1px solid var(--border); border-radius: 6px; background: #fff; min-width: 90px; }
.filters label.checkbox { display: flex; align-items: center; gap: 5px; font-size: 12.5px; color: var(--muted); }
.filters button { font-size: 12.5px; padding: 6px 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--card); cursor: pointer; color: var(--muted); }
.filters button.active { background: var(--text); color: #fff; border-color: var(--text); }
.sort-note { font-size: 11.5px; color: var(--mutedest); margin: 0 0 10px; }
.queue { background: var(--card); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.row { padding: 12px 16px; border-top: 1px solid var(--border); cursor: pointer; }
.row:first-child { border-top: none; }
.row:hover { background: #fafbfc; }
.row-main { display: flex; justify-content: space-between; align-items: flex-start; gap: 14px; }
.row-left { min-width: 0; }
.row-head { display: flex; gap: 8px; align-items: center; margin-bottom: 4px; flex-wrap: wrap; }
.pill { font-size: 11px; font-weight: 700; padding: 3px 9px; border-radius: 20px; letter-spacing: .02em; white-space: nowrap; }
.pill-buy { background: var(--buy-bg); color: var(--buy); }
.pill-watch { background: var(--watch-bg); color: var(--watch); }
.pill-risk { background: var(--risk-bg); color: var(--risk); }
.pill-pass { background: var(--pass-bg); color: var(--pass); }
.pill-unsupported { background: var(--unsupported-bg); color: var(--unsupported); }
.pill-legacy { background: var(--legacy-bg); color: var(--legacy); }
.score { font-size: 12px; color: var(--muted); }
.title { font-size: 14.5px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 520px; }
.source { font-size: 12px; color: var(--mutedest); }
.row-right { text-align: right; flex-shrink: 0; }
.price-line { font-size: 17px; font-weight: 600; white-space: nowrap; }
.price-line .arrow { color: var(--mutedest); font-weight: 400; font-size: 13px; }
.live-bid-flag { font-size: 10.5px; font-weight: 700; color: var(--warn); }
.profit-line { font-size: 13px; color: var(--text); }
.roi-line { font-size: 12px; color: var(--muted); }
.no-evidence-flag { font-size: 11px; color: var(--warn); margin-top: 2px; }
.detail { padding: 14px 18px 20px; background: #fafbfc; border-top: 1px solid var(--border); }
.detail .actions { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 4px; }
.detail a.open-listing, .detail a.view-evidence { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; color: var(--accent); border: 1px solid var(--border); padding: 7px 14px; border-radius: 8px; background: var(--card); text-decoration: none; }
.sechead { font-size: 11.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); margin: 16px 0 6px; }
.reasons { margin: 0; padding-left: 18px; font-size: 13px; }
.kv-row { display: flex; justify-content: space-between; font-size: 12.5px; padding: 3px 0; border-top: 1px solid var(--border); }
.kv-row:first-of-type { border-top: none; }
.kv-row.total { font-weight: 700; border-top: 1px solid var(--text); margin-top: 2px; padding-top: 5px; }
.note-box { font-size: 13px; padding: 9px 12px; background: var(--warn-bg); color: var(--warn); border-radius: 8px; margin-top: 6px; }
.conf-line { font-size: 13px; margin-top: 6px; }
.evidence-item { border-top: 1px solid var(--border); padding: 8px 0; font-size: 12.5px; }
.evidence-item:first-of-type { border-top: none; }
.evidence-top { display: flex; justify-content: space-between; gap: 10px; align-items: baseline; }
.evidence-badge { font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 4px; background: var(--pass-bg); color: var(--muted); margin-right: 6px; }
.evidence-badge.sold { background: var(--buy-bg); color: var(--buy); }
.evidence-meta { color: var(--muted); margin-top: 2px; }
.empty-note { font-size: 12.5px; color: var(--muted); font-style: italic; }
.missing-note { margin-top: 16px; font-size: 11.5px; color: var(--mutedest); border-top: 1px solid var(--border); padding-top: 10px; }
.empty-run { padding: 30px; text-align: center; color: var(--muted); font-size: 13px; }
.section-divider { margin: 22px 0 8px; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; color: var(--mutedest); }
</style>
</head>
"""

_HTML_BODY_START = """<body>
<header class="topbar">
  <div class="brand">Opportunity dashboard</div>
  <div class="status" id="status-line">Loading...</div>
</header>
<main>
  <div class="filters" id="filters"></div>
  <div class="sort-note">Sorted by decision (BUY first), then each item's own pipeline score. Discovery items use a 0&ndash;100 Flip Score; Daily Scan items use a 1&ndash;10 Score &mdash; these two scores are not directly comparable, so Daily Scan items are ranked as their own group.</div>
  <div class="queue" id="queue"></div>
</main>
<script id="discovery-report-data" type="application/json">"""

_HTML_MID = """</script>
<script id="legacy-scan-data" type="application/json">"""

_HTML_BODY_END = """</script>
"""

_HTML_SCRIPT = r"""<script>
(function () {
  var discoveryPayload = JSON.parse(document.getElementById('discovery-report-data').textContent);
  var legacyPayload = JSON.parse(document.getElementById('legacy-scan-data').textContent);

  var discoveryOpportunities = (discoveryPayload && discoveryPayload.opportunities) || [];
  var legacyRows = (legacyPayload && legacyPayload.rows) || [];

  var DECISION_ORDER = ['BUY', 'PROFITABLE BUT CAPITAL RISK', 'WATCH', 'PASS'];
  var PILL_CLASS = { 'BUY': 'pill-buy', 'WATCH': 'pill-watch', 'PASS': 'pill-pass', 'PROFITABLE BUT CAPITAL RISK': 'pill-risk' };
  // Sort tiers: real decisions rank by how actionable they are, unsupported
  // (unverified-source) WATCH items rank below verified ones since they were
  // never independently priced, legacy (no-decision) rows get their own
  // group ranked by their own native score, PASS is last.
  var TIER = {
    'BUY': 0, 'PROFITABLE BUT CAPITAL RISK': 1,
    'WATCH_VERIFIED': 2, 'LEGACY': 3, 'WATCH_UNSUPPORTED': 4, 'PASS': 5
  };

  var state = {
    pipeline: 'all', decision: 'all', category: 'all', source: 'all',
    minPrice: '', maxPrice: '', minRoi: '', minConfidence: '',
    showPass: false, hideNoConfidence: false
  };
  var expandedKey = null;

  function money(v) {
    if (v === null || v === undefined || v === '') return 'Not available';
    var n = Number(v);
    if (isNaN(n)) return 'Not available';
    var sign = n < 0 ? '-' : '';
    return sign + '$' + Math.round(Math.abs(n)).toLocaleString();
  }
  function pct(v) {
    if (v === null || v === undefined || v === '') return 'Not available';
    var n = Number(v);
    if (isNaN(n)) return 'Not available';
    return Math.round(n) + '%';
  }
  function na(v) {
    if (v === null || v === undefined || v === '') return 'Not available';
    return v;
  }
  function escapeHtml(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function escapeAttr(s) { return escapeHtml(s); }

  // ---- Build one common list of {pipeline, key, raw} without inventing
  // any business values -- every accessor below just reads the field a
  // given pipeline actually persisted, or returns "Not available"/null.
  var items = [];
  discoveryOpportunities.forEach(function (o, i) {
    items.push({ pipeline: 'discovery', key: 'd:' + (o.url || i), raw: o });
  });
  legacyRows.forEach(function (r, i) {
    items.push({ pipeline: 'legacy', key: 'l:' + (r.url || i), raw: r });
  });

  function title(it) { return it.raw.title || '(untitled)'; }
  function url(it) { return it.raw.url || ''; }
  function source(it) { return it.raw.source || 'Unknown source'; }
  function category(it) { return it.pipeline === 'legacy' ? (it.raw.category || 'Uncategorised') : null; }
  function decision(it) { return it.pipeline === 'discovery' ? it.raw.decision : null; }
  function isUnsupported(it) { return it.pipeline === 'discovery' && it.raw.verification_status && it.raw.verification_status !== 'verified'; }
  function priceIsLiveBid(it) {
    if (it.pipeline !== 'discovery') return false;
    return it.raw.price_type === 'starting_bid' || it.raw.price_type === 'current_bid';
  }
  function price(it) {
    if (it.pipeline === 'discovery') {
      return it.raw.current_price !== null && it.raw.current_price !== undefined ? it.raw.current_price : it.raw.buy_now_price;
    }
    return it.raw.price_nzd !== null && it.raw.price_nzd !== undefined ? it.raw.price_nzd : it.raw.buy_now_price_nzd;
  }
  function estResale(it) {
    if (it.pipeline === 'discovery') {
      var v = it.raw.valuation || {};
      return v.quick_sale_mid !== undefined && v.quick_sale_mid !== null ? v.quick_sale_mid : v.normal;
    }
    return it.raw.suggested_resale_price_nzd;
  }
  function estProfitLine(it) {
    if (it.pipeline === 'discovery') return money(it.raw.expected_net_profit_low) + '&ndash;' + money(it.raw.expected_net_profit_high);
    return money(it.raw.potential_profit_nzd);
  }
  function roiLine(it) {
    if (it.pipeline === 'discovery') return pct(it.raw.roi_low_pct) + '&ndash;' + pct(it.raw.roi_high_pct);
    return pct(it.raw.potential_profit_pct);
  }
  function roiForFilter(it) {
    if (it.pipeline === 'discovery') return it.raw.roi_low_pct;
    return it.raw.potential_profit_pct;
  }
  function confidence(it) {
    if (it.pipeline === 'discovery') return (it.raw.valuation || {}).confidence_pct;
    return null;
  }
  function liquidityLabel(it) {
    if (it.pipeline === 'discovery') return na(it.raw.liquidity);
    return it.raw.resale_likelihood ? (it.raw.resale_likelihood + ' (resale likelihood)') : 'Not available';
  }
  function nativeScoreLine(it) {
    if (it.pipeline === 'discovery') {
      return (it.raw.flip_score === null || it.raw.flip_score === undefined ? 'Not available' : it.raw.flip_score + '/100') +
        (it.raw.flip_score_band ? ' &middot; ' + it.raw.flip_score_band.toLowerCase() : '');
    }
    return (it.raw.score === null || it.raw.score === undefined ? 'Not available' : it.raw.score + '/10');
  }
  function nativeScoreForSort(it) {
    return it.pipeline === 'discovery' ? (it.raw.flip_score || 0) : (it.raw.score || 0);
  }
  function condition(it) { return it.pipeline === 'legacy' ? (it.raw.condition || 'Not available') : 'Not available'; }
  function location(it) { return it.pipeline === 'legacy' ? (it.raw.location || 'Not available') : 'Not available'; }
  function closingDate(it) { return it.pipeline === 'discovery' ? (it.raw.closing_date || 'Not available') : 'Not available'; }
  function reserveStatus(it) { return it.pipeline === 'discovery' ? (it.raw.reserve_status || 'Not available') : 'Not available'; }
  function evidenceQuality(it) {
    if (it.pipeline === 'discovery') {
      if (it.raw.verification_status !== 'verified') {
        return { label: 'Unverified source (not independently priced)', cls: 'pill-unsupported' };
      }
      var n = ((it.raw.valuation || {}).evidence || []).length;
      return { label: 'Verified listing &middot; ' + n + ' comparable' + (n === 1 ? '' : 's'), cls: 'pill-buy' };
    }
    return { label: it.raw.data_basis || 'Not available', cls: it.raw.data_basis === 'Real price + condition' ? 'pill-buy' : 'pill-watch' };
  }
  function sortTier(it) {
    if (it.pipeline === 'legacy') return TIER.LEGACY;
    var d = it.raw.decision;
    if (d === 'BUY') return TIER.BUY;
    if (d === 'PROFITABLE BUT CAPITAL RISK') return TIER['PROFITABLE BUT CAPITAL RISK'];
    if (d === 'WATCH') return isUnsupported(it) ? TIER.WATCH_UNSUPPORTED : TIER.WATCH_VERIFIED;
    return TIER.PASS;
  }

  // ---- Filter option lists, built from whatever data actually exists ----
  function uniqueSorted(vals) {
    var seen = {}; var out = [];
    vals.forEach(function (v) { if (v && !seen[v]) { seen[v] = true; out.push(v); } });
    out.sort();
    return out;
  }
  var categories = uniqueSorted(items.map(category).filter(Boolean));
  var sources = uniqueSorted(items.map(source));

  function renderFilters() {
    var el = document.getElementById('filters');
    el.innerHTML =
      field('Pipeline', selectHtml('f-pipeline', [['all', 'All'], ['discovery', 'Discovery'], ['legacy', 'Daily scan']], state.pipeline)) +
      field('Decision', selectHtml('f-decision', [['all', 'All'], ['BUY', 'BUY'], ['PROFITABLE BUT CAPITAL RISK', 'CAPITAL RISK'], ['WATCH', 'WATCH'], ['PASS', 'PASS'], ['NONE', 'No decision (Daily scan)']], state.decision)) +
      (categories.length ? field('Category', selectHtml('f-category', [['all', 'All']].concat(categories.map(function (c) { return [c, c]; })), state.category)) : '') +
      field('Source', selectHtml('f-source', [['all', 'All']].concat(sources.map(function (s) { return [s, s]; })), state.source)) +
      field('Min price', '<input type="number" id="f-min-price" value="' + escapeAttr(state.minPrice) + '">') +
      field('Max price', '<input type="number" id="f-max-price" value="' + escapeAttr(state.maxPrice) + '">') +
      field('Min ROI/profit %', '<input type="number" id="f-min-roi" value="' + escapeAttr(state.minRoi) + '">') +
      field('Min confidence %', '<input type="number" id="f-min-confidence" value="' + escapeAttr(state.minConfidence) + '">') +
      '<label class="checkbox"><input type="checkbox" id="f-hide-no-confidence"' + (state.hideNoConfidence ? ' checked' : '') + '> Hide items with no confidence data</label>' +
      '<button id="toggle-pass" class="' + (state.showPass ? 'active' : '') + '">' + (state.showPass ? 'Hide passed' : 'Show passed') + '</button>';

    function field(label, inner) { return '<div class="field"><span>' + label + '</span>' + inner + '</div>'; }
    function selectHtml(id, options, current) {
      return '<select id="' + id + '">' + options.map(function (o) {
        return '<option value="' + escapeAttr(o[0]) + '"' + (o[0] === current ? ' selected' : '') + '>' + escapeHtml(o[1]) + '</option>';
      }).join('') + '</select>';
    }

    document.getElementById('f-pipeline').addEventListener('change', function () { state.pipeline = this.value; render(); });
    document.getElementById('f-decision').addEventListener('change', function () { state.decision = this.value; render(); });
    if (document.getElementById('f-category')) document.getElementById('f-category').addEventListener('change', function () { state.category = this.value; render(); });
    document.getElementById('f-source').addEventListener('change', function () { state.source = this.value; render(); });
    document.getElementById('f-min-price').addEventListener('input', function () { state.minPrice = this.value; render(); });
    document.getElementById('f-max-price').addEventListener('input', function () { state.maxPrice = this.value; render(); });
    document.getElementById('f-min-roi').addEventListener('input', function () { state.minRoi = this.value; render(); });
    document.getElementById('f-min-confidence').addEventListener('input', function () { state.minConfidence = this.value; render(); });
    document.getElementById('f-hide-no-confidence').addEventListener('change', function () { state.hideNoConfidence = this.checked; render(); });
    document.getElementById('toggle-pass').addEventListener('click', function () { state.showPass = !state.showPass; render(); });
  }

  function renderStatus() {
    var counts = DECISION_ORDER.map(function (d) {
      return ((discoveryPayload && discoveryPayload.decision_counts && discoveryPayload.decision_counts[d]) || 0) + ' ' + d;
    }).join(' &middot; ');
    var discTs = discoveryPayload && discoveryPayload.run_timestamp ? new Date(discoveryPayload.run_timestamp).toLocaleString() : 'no discovery run yet';
    var legTs = legacyPayload && legacyPayload.run_timestamp ? new Date(legacyPayload.run_timestamp).toLocaleString() : 'no daily scan run yet';
    var unsupportedCount = discoveryOpportunities.filter(isUnsupportedRaw).length;
    var html =
      '<div class="status-row">Discovery (Phase 3): <b>' + discTs + '</b> &middot; ' + discoveryOpportunities.length + ' opportunities &middot; ' + counts +
      (unsupportedCount ? ' &middot; ' + unsupportedCount + ' unverified-source WATCH (unpriced)' : '') + '</div>' +
      '<div class="status-row">Daily scan (Phase 2, no BUY/WATCH/PASS decision field): <b>' + legTs + '</b> &middot; ' + legacyRows.length + ' items</div>';
    document.getElementById('status-line').innerHTML = html;
  }
  function isUnsupportedRaw(o) { return o.verification_status && o.verification_status !== 'verified'; }

  function passFilters(it) {
    if (state.pipeline !== 'all' && it.pipeline !== state.pipeline) return false;
    if (!state.showPass && sortTier(it) === TIER.PASS) return false;
    if (state.decision !== 'all') {
      if (state.decision === 'NONE') { if (it.pipeline !== 'legacy') return false; }
      else if (decision(it) !== state.decision) return false;
    }
    if (state.category !== 'all' && category(it) !== state.category) return false;
    if (state.source !== 'all' && source(it) !== state.source) return false;
    var p = price(it);
    if (state.minPrice !== '' && (p === null || p === undefined || Number(p) < Number(state.minPrice))) return false;
    if (state.maxPrice !== '' && (p === null || p === undefined || Number(p) > Number(state.maxPrice))) return false;
    if (state.minRoi !== '') {
      var r = roiForFilter(it);
      if (r === null || r === undefined || Number(r) < Number(state.minRoi)) return false;
    }
    var conf = confidence(it);
    if (state.hideNoConfidence && (conf === null || conf === undefined)) return false;
    if (state.minConfidence !== '' && (conf === null || conf === undefined || Number(conf) < Number(state.minConfidence))) return false;
    return true;
  }

  function sortedItems() {
    var list = items.filter(passFilters);
    list.sort(function (a, b) {
      var ta = sortTier(a), tb = sortTier(b);
      if (ta !== tb) return ta - tb;
      return nativeScoreForSort(b) - nativeScoreForSort(a);
    });
    return list;
  }

  function evidenceTag(type) {
    var cls = type === 'SOLD' ? 'evidence-badge sold' : 'evidence-badge';
    return '<span class="' + cls + '">' + (type || 'OTHER').replace('_', ' ').toLowerCase() + '</span>';
  }

  function renderDiscoveryDetail(it) {
    var o = it.raw;
    var val = o.valuation || {};
    var costs = o.costs || {};
    var ident = o.identification || {};
    var reasons = (o.decision_reasons || []).map(function (r) { return '<li>' + escapeHtml(r) + '</li>'; }).join('');

    var identLine = [ident.brand, ident.model].filter(Boolean).join(' ') || 'Brand/model not identified';
    if (ident.is_bundle) identLine += ' &middot; bundle/lot';
    var identSub = 'Condition risk: ' + (ident.condition_risk_level || 'unknown') +
      (ident.condition_risk_phrases && ident.condition_risk_phrases.length ? ' (' + ident.condition_risk_phrases.join(', ') + ')' : '') +
      ' &middot; ' + (ident.model_identified_confidently ? 'model identified confidently' : 'model not confidently identified');

    var valLine = 'Quick sale ' + money(val.quick_sale_low) + '&ndash;' + money(val.quick_sale_high) +
      ' (mid ' + money(val.quick_sale_mid) + ') &middot; normal ' + money(val.normal) + ' &middot; optimistic ' + money(val.optimistic);

    var confBlock;
    if (val.evidence_note) {
      confBlock = '<div class="note-box">' + escapeHtml(val.evidence_note) +
        '<div style="margin-top:3px;font-size:11.5px;opacity:.85;">Valuation confidence: ' + pct(val.confidence_pct) + '</div></div>';
    } else {
      confBlock = '<div class="conf-line">Valuation confidence: ' + pct(val.confidence_pct) + '</div>';
    }

    var costRows = [
      ['Purchase price', costs.purchase_price], ["Buyer's premium", costs.buyer_premium],
      ['GST', costs.gst], ['Selling fees', costs.selling_fees], ['Payment fees', costs.payment_fees],
      ['Shipping', costs.shipping], ['Packaging', costs.packaging], ['Repair allowance', costs.repair_allowance],
      ['Negotiation allowance', costs.negotiation_allowance], ['Other', costs.other],
    ].filter(function (r) { return r[1] !== null && r[1] !== undefined; })
     .map(function (r) { return '<div class="kv-row"><span>' + r[0] + '</span><span>' + money(r[1]) + '</span></div>'; }).join('');
    costRows += '<div class="kv-row"><span>Total excluding purchase</span><span>' + money(costs.total_excluding_purchase) + '</span></div>';
    costRows += '<div class="kv-row total"><span>Total</span><span>' + money(costs.total) + '</span></div>';

    var evidence = val.evidence || [];
    var evidenceHtml;
    if (!evidence.length) {
      evidenceHtml = '<div class="empty-note">No comparable evidence found for this listing.</div>';
    } else {
      evidenceHtml = evidence.map(function (e) {
        var name = [e.product, e.model].filter(Boolean).join(' ');
        var convertedNote = (e.original_currency && e.original_price !== null && e.original_price !== undefined)
          ? ' (converted from ' + escapeHtml(e.original_currency) + ' ' + e.original_price + ')' : '';
        return '<div class="evidence-item" id="evidence-anchor-' + escapeAttr(it.key) + '">' +
          '<div class="evidence-top"><span>' + evidenceTag(e.evidence_type) +
          '<a href="' + escapeAttr(e.url) + '" target="_blank" rel="noopener">' + escapeHtml(name || e.url) + '</a></span>' +
          '<span>' + escapeHtml(e.currency || '') + ' ' + money(e.price) + convertedNote + '</span></div>' +
          '<div class="evidence-meta">' + escapeHtml(e.source || 'unknown source') + ' &middot; condition: ' + escapeHtml(e.condition || 'unknown') +
          ' &middot; ' + Math.round((e.similarity_score || 0) * 100) + '% title match &middot; observed ' + escapeHtml(e.date_observed || 'unknown date') +
          ' &middot; ' + (e.is_sold ? 'confirmed sale' : 'asking price only') + '</div>' +
          '</div>';
      }).join('');
    }

    var capitalLine = '';
    if (o.decision === 'PROFITABLE BUT CAPITAL RISK' && o.capital_concentration_pct !== null && o.capital_concentration_pct !== undefined) {
      capitalLine = '<div style="font-size:13px;margin-top:4px;">' + Math.round(o.capital_concentration_pct) + '% of bankroll</div>';
    }

    var liveBidNote = priceIsLiveBid(it)
      ? '<div class="note-box">This is a live auction ' + (o.price_type === 'starting_bid' ? 'starting bid' : 'current bid') + ', not a confirmed acquisition price. It can rise before close.</div>'
      : '';
    var auctionBlock =
      '<div class="sechead">Auction context</div>' +
      '<div class="kv-row"><span>Closing time</span><span>' + escapeHtml(closingDate(it)) + '</span></div>' +
      '<div class="kv-row"><span>Reserve status</span><span>' + escapeHtml(reserveStatus(it)) + '</span></div>' +
      '<div class="kv-row"><span>Verification status</span><span>' + escapeHtml(o.verification_status || 'unknown') + '</span></div>' +
      liveBidNote;

    return '<div class="detail">' +
      '<div class="actions">' +
      '<a class="open-listing" href="' + escapeAttr(o.url) + '" target="_blank" rel="noopener">Open original listing &#8599;</a>' +
      '<a class="view-evidence" href="#evidence-anchor-' + escapeAttr(it.key) + '">View evidence &#8595;</a>' +
      '</div>' +
      capitalLine +
      auctionBlock +
      '<div class="sechead">Decision reasons</div><ul class="reasons">' + (reasons || '<li>none recorded</li>') + '</ul>' +
      '<div class="sechead">Product identification</div><div style="font-size:13px;">' + escapeHtml(identLine) + '</div>' +
      '<div style="font-size:12px;color:var(--muted);">' + escapeHtml(identSub) + '</div>' +
      '<div class="sechead">Valuation (scanner-generated estimate, not a verified fact)</div><div style="font-size:13px;">' + valLine + '</div>' + confBlock +
      '<div class="sechead">Cost breakdown</div>' + costRows +
      '<div class="sechead">Comparable evidence (' + evidence.length + ')</div>' + evidenceHtml +
      '<div class="missing-note">Condition, listing location, image, and seller status are not currently part of the discovery pipeline’s persisted output for this item.</div>' +
      '</div>';
  }

  function renderLegacyDetail(it) {
    var r = it.raw;
    var links = [
      ['Trade Me search', r.trademe_search_url], ['Facebook search', r.facebook_search_url], ['eBay sold search', r.ebay_search_url],
    ].filter(function (l) { return l[1]; }).map(function (l) {
      return '<a href="' + escapeAttr(l[1]) + '" target="_blank" rel="noopener">' + escapeHtml(l[0]) + ' &#8599;</a>';
    }).join(' &middot; ');

    return '<div class="detail">' +
      '<div class="actions">' +
      '<a class="open-listing" href="' + escapeAttr(r.url) + '" target="_blank" rel="noopener">Open original listing &#8599;</a>' +
      '</div>' +
      '<div class="sechead">Evidence basis</div><div style="font-size:13px;">' + escapeHtml(r.data_basis || 'Not available') +
      ' &mdash; ' + (r.data_basis === 'Real price + condition' ? 'real Turners catalog price/condition' : 'auction-event listing language only, not an individually priced/verified item') + '</div>' +
      '<div class="sechead">Auction / listing context</div>' +
      '<div class="kv-row"><span>Condition</span><span>' + escapeHtml(condition(it)) + '</span></div>' +
      '<div class="kv-row"><span>Location</span><span>' + escapeHtml(location(it)) + '</span></div>' +
      '<div class="kv-row"><span>Reserve / closing (free text as recorded)</span><span>' + escapeHtml(r.notes || 'Not available') + '</span></div>' +
      '<div class="sechead">Score (1&ndash;10, legacy pipeline)</div><div style="font-size:13px;">' + escapeHtml(nativeScoreLine(it)) + '</div>' +
      '<ul class="reasons">' + (r.reasons ? String(r.reasons).split(';').map(function (x) { return '<li>' + escapeHtml(x.trim()) + '</li>'; }).join('') : '<li>none recorded</li>') + '</ul>' +
      '<div style="font-size:13px;">' + escapeHtml(r.explanation || '') + '</div>' +
      '<div class="sechead">Estimated new price (rough sanity check, not a quote)</div><div style="font-size:13px;">' + money(r.estimated_new_price_nzd) + (r.value_vs_new_pct !== null && r.value_vs_new_pct !== undefined ? ' &middot; ' + pct(r.value_vs_new_pct) + ' below new' : '') + '</div>' +
      '<div class="sechead">Suggested resale (estimate, not a verified fact)</div><div style="font-size:13px;">' + money(r.suggested_resale_price_nzd) + '</div>' +
      '<div class="sechead">Potential profit</div><div style="font-size:13px;">' + money(r.potential_profit_nzd) + ' (' + pct(r.potential_profit_pct) + ') &middot; resale likelihood: ' + escapeHtml(r.resale_likelihood || 'Not available') + '</div>' +
      '<div style="font-size:12px;color:var(--muted);">' + escapeHtml(r.resale_reason || '') + '</div>' +
      (links ? '<div class="sechead">Manual comparable checks</div><div style="font-size:13px;">' + links + '</div>' : '') +
      '<div class="missing-note">Flip score, valuation confidence, ROI range, liquidity classification, max buy price, and structured comparable evidence are not part of the legacy daily-scan pipeline’s persisted output &mdash; this item was scored 1–10 by a separate, older code path. Reserve status and closing time exist only as free text inside "notes", not as separate fields.</div>' +
      '</div>';
  }

  function renderRow(it) {
    var pipelineTag = it.pipeline === 'legacy'
      ? '<span class="pill pill-legacy">DAILY SCAN</span>'
      : '';
    var d = decision(it);
    var decisionPill = d
      ? '<span class="pill ' + (PILL_CLASS[d] || 'pill-pass') + '">' + escapeHtml(d) + '</span>'
      : '<span class="pill pill-legacy">NO DECISION</span>';
    var eq = evidenceQuality(it);
    var unsupportedPill = isUnsupported(it) ? '<span class="pill pill-unsupported">UNVERIFIED SOURCE</span>' : '';

    var liveBidFlag = priceIsLiveBid(it) ? '<div class="live-bid-flag">Live bid &mdash; not final price</div>' : '';
    var noEvidenceFlag = (it.pipeline === 'discovery' && (!it.raw.valuation || !(it.raw.valuation.evidence || []).length))
      ? '<div class="no-evidence-flag">No comparable evidence</div>' : '';

    var maxBuy = it.pipeline === 'discovery' ? money(it.raw.max_buy_price) : 'Not available';

    var rowHtml =
      '<div class="row-main">' +
      '<div class="row-left">' +
      '<div class="row-head">' + pipelineTag + decisionPill + unsupportedPill +
      '<span class="score">' + nativeScoreLine(it) + '</span>' +
      '</div>' +
      '<div class="title">' + escapeHtml(title(it)) + '</div>' +
      '<div class="source">' + escapeHtml(source(it)) + (category(it) ? ' &middot; ' + escapeHtml(category(it)) : '') + ' &middot; ' + escapeHtml(eq.label) + '</div>' +
      '</div>' +
      '<div class="row-right">' +
      '<div class="price-line">' + money(price(it)) + '<span class="arrow"> &rarr; </span>' + maxBuy + '</div>' +
      liveBidFlag +
      '<div class="profit-line">profit ' + estProfitLine(it) + '</div>' +
      '<div class="roi-line">roi/margin ' + roiLine(it) + '</div>' +
      noEvidenceFlag +
      '</div>' +
      '</div>';

    var row = document.createElement('div');
    row.className = 'row';
    row.dataset.key = it.key;
    row.innerHTML = rowHtml;
    row.addEventListener('click', function (e) {
      if (e.target.closest('a')) return;
      expandedKey = (expandedKey === it.key) ? null : it.key;
      render();
    });

    if (expandedKey === it.key) {
      var detailWrap = document.createElement('div');
      detailWrap.innerHTML = it.pipeline === 'discovery' ? renderDiscoveryDetail(it) : renderLegacyDetail(it);
      detailWrap.firstChild.addEventListener('click', function (e) { e.stopPropagation(); });
      row.appendChild(detailWrap.firstChild);
    }
    return row;
  }

  function render() {
    renderFilters();
    var queue = document.getElementById('queue');
    queue.innerHTML = '';
    var list = sortedItems();
    if (!list.length) {
      var empty = document.createElement('div');
      empty.className = 'empty-run';
      empty.textContent = (discoveryOpportunities.length + legacyRows.length) === 0
        ? 'No scanner runs have been persisted yet.'
        : 'No opportunities match the current filters.';
      queue.appendChild(empty);
      return;
    }
    list.forEach(function (it) { queue.appendChild(renderRow(it)); });
  }

  renderStatus();
  render();
})();
</script>
"""

_HTML_FOOT = """</body>
</html>
"""
