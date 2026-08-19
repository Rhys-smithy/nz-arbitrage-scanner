"""Phase 4B.3 (+ 4B.8 Opportunity Dashboard, + Command Centre) -- a static
HTML view over the persisted Opportunity results from BOTH scanner
pipelines.

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
- Bankroll reference figures (``config.json``'s ``bankroll`` block): the
  same static starting/target bankroll numbers already used elsewhere
  (``scanner/bankroll.py``, ``scanner/flip_score.py``) to compute every
  opportunity's capital-concentration percentage and BUY/WATCH/PASS
  decision. Read-only, and only the two static reference figures --
  never a live available/committed-capital number, since nothing in the
  codebase tracks that yet (see PROJECT_STATE.md).

Every number, label, and grouping the page displays is produced
client-side, in JavaScript, by reading straight from the embedded
payloads -- there is no second schema and no Python-side transformation
of Opportunity data beyond (a) locating the latest run of each pipeline,
(b) converting the legacy CSV's known-numeric text columns to
numbers/None so the UI can treat them the same way it treats discovery's
numbers, and (c) reading the two static bankroll figures out of
config.json. None of these steps recomputes or reinterprets any
valuation/scoring/decision value.

The "Command Centre" home section (top opportunities, summary metrics,
browse-by-source breakdown) is a presentation layer only: it re-sorts and
re-groups the exact same already-computed fields the original Deal Queue
list already rendered, using the exact same tier/score ranking the list
below already used (``sortTier`` / ``nativeScoreForSort``). It does not
introduce a second Flip Score, confidence model, or profitability
calculation, and it does not merge Discovery and legacy-pipeline records
into a fake unified schema -- each item keeps its own pipeline's native
fields and is tagged accordingly, exactly as the original list already
did.

The page is a single static file with inline CSS/JS (no build step, no
new dependency, no server) so it opens directly via file:// -- consistent
with how reports/opportunities_*.csv|xlsx already work today.

Hunting (starring) -- a third, independent payload
---------------------------------------------------
As of this module's Hunting slice, a third payload is embedded alongside
the discovery and legacy ones: a read-only snapshot of
``data/hunting_state.json`` (via ``scanner/hunting_store.py``), which
holds only user-authored workflow state (starred/notes/target-offer
override), never scanner-generated data. It is loaded exactly like the
other two -- read verbatim, never computed or reinterpreted here -- and
kept in its own script tag so it stays visually and structurally separate
from scanner output.

The discovery and legacy payloads embedded on the page are untouched by
this addition -- exactly the same dicts loaded from disk, with nothing
added, removed, or recomputed (this is asserted directly by
``tests/test_deal_queue_report.py``'s exact round-trip test). Matching a
row to its Hunting record is instead done entirely client-side: the
page's JS mirrors ``scanner.search.util.canonicalize_url()`` well enough
to compute the same ``source + canonical URL`` key
``scanner.hunting_store.make_key()`` uses, from each row's own existing
``source``/``url`` fields, at render time. That JS mirror is documented
in-line where it's defined and is a client-side approximation only --
the server (``scanner/dashboard_server.py``) always computes the
authoritative key itself from the raw ``source``/``url`` a star/unstar
request sends it, so an edge case where the two disagree could only ever
affect whether a row's star renders as already-filled, never whether
starring/unstarring itself works.

Because a star can happen at any moment (not just at scan time), a
starred item must survive a plain browser refresh, not only the next
scanner run -- an embedded snapshot alone only updates when this module
next regenerates the HTML. See ``scanner/dashboard_server.py`` for the
local process that serves this same JSON live, and this page's own
client-side JS for how it upgrades from "read the embedded snapshot" to
"fetch the live state" when that server happens to be running.
"""
from __future__ import annotations

import csv
import json
import os
from typing import Optional

from scanner.discovery_report import DEFAULT_INDEX_PATH, REPORTS_DIR
from scanner.hunting_store import DEFAULT_PATH as DEFAULT_HUNTING_STATE_PATH
from scanner.hunting_store import load_hunting_state

DEFAULT_OUTPUT_PATH = os.path.join(REPORTS_DIR, "deal_queue.html")

# reports/index.json -- the manifest main.py/scanner/report.py already
# maintain for the legacy scan pipeline's CSV/XLSX reports. Unrelated to
# discovery_index.json (different pipeline, different schema).
LEGACY_INDEX_PATH = os.path.join(REPORTS_DIR, "index.json")

# config.json -- lives one directory up from reports/. Only used to read
# the static bankroll reference figures (see load_bankroll_config below).
DEFAULT_CONFIG_PATH = os.path.join(REPORTS_DIR, "..", "config.json")

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


def load_bankroll_config(config_path: str = DEFAULT_CONFIG_PATH) -> Optional[dict]:
    """Reads config.json's "bankroll" block and returns only the two
    static reference figures the Command Centre needs:
    ``starting_bankroll`` and ``target_bankroll``. These are the exact
    same numbers scanner/bankroll.py and scanner/flip_score.py already
    use, at run time, to compute every persisted opportunity's
    capital_concentration_pct and BUY/WATCH/PASS decision -- so this is
    read-only exposure of an existing authoritative value, not a new
    computation.

    Deliberately never reads/returns available_cash, inventory_value, or
    realised_profit -- nothing in this codebase currently tracks or
    persists those, so surfacing them here would be inventing a number
    the rest of the system doesn't actually have.

    Returns None (not a fabricated default) if config.json is missing,
    unreadable, or has no usable bankroll figures, so the UI can omit the
    line entirely rather than invent one.
    """
    if not os.path.exists(config_path):
        return None
    try:
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    bankroll = config.get("bankroll")
    if not isinstance(bankroll, dict):
        return None

    starting = bankroll.get("starting_bankroll")
    target = bankroll.get("target_bankroll")
    if starting is None and target is None:
        return None

    return {"starting_bankroll": starting, "target_bankroll": target}


def load_hunting_payload(hunting_state_path: str = DEFAULT_HUNTING_STATE_PATH) -> dict:
    """Reads data/hunting_state.json via scanner.hunting_store (same
    missing/corrupt-file -> {} handling as that module) and returns it
    wrapped as {"hunting": {...}} -- the exact shape
    scanner/dashboard_server.py's live GET /api/hunting endpoint also
    returns, so the page's client-side JS has one parsing path for both
    the embedded snapshot and a live fetch(). Never returns None: an
    absent/corrupt file is legitimately "nothing hunted yet", not "no run
    has happened", so unlike the two loaders above this always yields a
    well-formed (possibly empty) payload rather than None."""
    return {"hunting": load_hunting_state(hunting_state_path)}


def render_latest_deal_queue(
    index_path: str = DEFAULT_INDEX_PATH,
    legacy_index_path: Optional[str] = None,
    reports_dir: str = REPORTS_DIR,
    output_path: str = DEFAULT_OUTPUT_PATH,
    config_path: Optional[str] = None,
    hunting_state_path: Optional[str] = None,
) -> Optional[str]:
    """Loads the latest persisted discovery payload AND the latest
    persisted legacy-scan payload -- independently; neither pipeline's
    data is merged, recomputed, or reinterpreted -- plus the static
    bankroll reference figures and the current Hunting state, and writes
    all four into reports/deal_queue.html (a fixed filename, overwritten
    every run, so there's always one current view to open -- the
    timestamped JSON/CSV files remain the historical record).

    `config_path` defaults to `<reports_dir>/../config.json` (computed at
    call time, not import time), mirroring `legacy_index_path`'s
    reports_dir-relative default -- so a caller/test that only overrides
    `reports_dir` still gets an isolated default instead of silently
    reading the real repo's config.json. `hunting_state_path` defaults to
    scanner.hunting_store.DEFAULT_PATH (data/hunting_state.json) the same
    way, resolved at call time so test isolation works the same as the
    other two.

    Returns the path written, or None only if NEITHER pipeline has ever
    produced a persisted run (nothing to show at all) -- Hunting state
    alone, with no scanner data at all, is never enough to render a page,
    since there would be nothing for a star to attach to."""
    discovery_payload = load_latest_discovery_payload(index_path=index_path, reports_dir=reports_dir)
    legacy_payload = load_latest_legacy_scan_payload(legacy_index_path=legacy_index_path, reports_dir=reports_dir)
    if discovery_payload is None and legacy_payload is None:
        return None

    if config_path is None:
        config_path = os.path.join(reports_dir, "..", "config.json")
    bankroll_cfg = load_bankroll_config(config_path=config_path)

    if hunting_state_path is None:
        hunting_state_path = DEFAULT_HUNTING_STATE_PATH
    hunting_payload = load_hunting_payload(hunting_state_path=hunting_state_path)

    # discovery_payload/legacy_payload are embedded exactly as loaded --
    # no copy, no added field, no recomputation. See the module docstring's
    # "Hunting (starring)" section for how the page matches a row to its
    # Hunting record without needing this module to touch either payload.
    html = _render_html(discovery_payload, legacy_payload, bankroll_cfg, hunting_payload)
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


def _render_html(
    discovery_payload: Optional[dict],
    legacy_payload: Optional[dict] = None,
    bankroll_cfg: Optional[dict] = None,
    hunting_payload: Optional[dict] = None,
) -> str:
    if hunting_payload is None:
        hunting_payload = {"hunting": {}}
    return (
        _HTML_HEAD
        + _HTML_STYLE
        + _HTML_BODY_START
        + _embed(discovery_payload)
        + _HTML_MID_1
        + _embed(legacy_payload)
        + _HTML_MID_2
        + _embed(bankroll_cfg)
        + _HTML_MID_3
        + _embed(hunting_payload)
        + _HTML_BODY_END
        + _HTML_SCRIPT
        + _HTML_FOOT
    )


_HTML_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Opportunity dashboard &middot; Command Centre</title>
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
body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; font-variant-numeric: tabular-nums; }
a { color: var(--accent); }
header.topbar { background: linear-gradient(135deg, #0a0f1a 0%, #16202c 100%); color: #fff; padding: 22px 22px 20px; }
header.topbar .topbar-inner { max-width: 1180px; margin: 0 auto; }
header.topbar .hello-row { display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 12px; }
header.topbar .hello { font-size: 23px; font-weight: 700; letter-spacing: -.01em; }
header.topbar .hello-sub { font-size: 11.5px; color: #93a3b8; text-transform: uppercase; letter-spacing: .07em; font-weight: 600; margin-top: 3px; }
header.topbar .status { color: #b9c4d3; font-size: 12px; text-align: right; max-width: 320px; line-height: 1.7; }
header.topbar .status b { color: #fff; font-weight: 600; }
header.topbar .status-row { margin-top: 2px; }
main { max-width: 1180px; margin: 0 auto; padding: 18px 16px 60px; }

.command-centre { margin-bottom: 8px; }
.metrics-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); align-items: stretch; gap: 10px; margin: 4px 0 24px; }
.metric-tile { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 12px 16px; display: flex; flex-direction: column; }
/* Dedicated metric-value color modifiers -- deliberately namespaced
   (metric-value-*) rather than reusing the .pill-buy/.pill-watch/etc
   badge classes used elsewhere on the page. Those badge classes carry
   their own background-color rule (e.g. ".pill-buy { background: ... }"),
   and CSS matches by class name regardless of which element wears it --
   reusing them here previously leaked that badge background onto these
   tiles as an unintended colored band behind the number. */
.metric-value { font-size: 25px; font-weight: 700; line-height: 1.1; }
.metric-value-buy { color: var(--buy); }
.metric-value-watch { color: var(--watch); }
.metric-value-risk { color: var(--risk); }
.metric-value-pass { color: var(--pass); }
.metric-value-legacy { color: var(--legacy); }
.metric-label { font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin-top: 5px; }
.metric-note { font-size: 10.5px; color: var(--mutedest); margin-top: 3px; }
.metric-caveat { grid-column: 1 / -1; font-size: 11px; color: var(--mutedest); font-style: italic; margin-top: 2px; }

.section-block { margin-bottom: 28px; }
.section-title-row { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
.section-title-row h2 { font-size: 15.5px; font-weight: 700; margin: 0; letter-spacing: -.005em; }
.section-note { font-size: 11.5px; color: var(--mutedest); }
.top-cap-note { margin-top: 10px; }

.no-buy-banner { font-size: 12.5px; padding: 10px 14px; background: var(--watch-bg); color: var(--watch); border-radius: 8px; margin-bottom: 10px; font-weight: 600; }
.all-buy-banner { font-size: 12.5px; padding: 10px 14px; background: var(--buy-bg); color: var(--buy); border-radius: 8px; margin-bottom: 10px; font-weight: 600; }

.top-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 12px; align-items: start; }
.top-grid .row.top-card { border: 1px solid var(--border); border-radius: 12px; background: var(--card); border-top: 1px solid var(--border); box-shadow: 0 1px 2px rgba(16,24,40,.05); margin: 0; }
.top-grid .row.top-card.top-card-buy { border-left: 4px solid var(--buy); }
.top-grid .row.top-card.top-card-risk { border-left: 4px solid var(--risk); }
.top-grid .row.top-card.top-card-watch { border-left: 4px solid var(--watch); }
.top-grid .row.top-card.top-card-legacy { border-left: 4px solid var(--legacy); }

.browse-grid { display: flex; flex-wrap: wrap; gap: 8px; }
.browse-tile { border: 1px solid var(--border); background: var(--card); border-radius: 9px; padding: 9px 15px; cursor: pointer; text-align: left; font: inherit; color: var(--text); }
.browse-tile:hover { background: #fafbfc; border-color: var(--accent); }
.browse-count { font-size: 17px; font-weight: 700; }
.browse-label { font-size: 11px; color: var(--muted); margin-top: 1px; }
.browse-subhead { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; color: var(--mutedest); margin: 14px 0 6px; }
.browse-pills { display: flex; flex-wrap: wrap; gap: 6px; }
.browse-pill { border: 1px solid var(--border); background: var(--card); border-radius: 20px; padding: 5px 12px; font-size: 12px; cursor: pointer; color: var(--text); font: inherit; }
.browse-pill:hover { background: #fafbfc; border-color: var(--accent); }
.browse-pill span { color: var(--mutedest); margin-left: 4px; }

.all-opportunities { border-top: 1px solid var(--border); padding-top: 22px; }
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
.top-grid .row.top-card:hover { background: #fff; border-color: var(--accent); }
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
.confidence-chip { font-size: 12px; color: var(--muted); }
.confidence-chip::before { content: "·"; margin-right: 8px; color: var(--mutedest); }
.title { font-size: 14.5px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 520px; }
.source { font-size: 12px; color: var(--mutedest); }
.row-right { text-align: right; flex-shrink: 0; }
.price-line { display: flex; align-items: baseline; justify-content: flex-end; gap: 8px; }
.price-block { display: inline-flex; flex-direction: column; align-items: flex-end; line-height: 1.15; }
.price-figure { font-size: 16.5px; font-weight: 700; white-space: nowrap; }
.price-label { font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; color: var(--mutedest); margin-top: 1px; }
.price-line .arrow { color: var(--mutedest); font-weight: 400; font-size: 13px; }
.live-bid-flag { font-size: 10.5px; font-weight: 700; color: var(--warn); text-align: right; }
.profit-line { font-size: 13px; color: var(--text); text-align: right; }
.roi-line { font-size: 12px; color: var(--muted); text-align: right; }
.no-evidence-flag { font-size: 11px; color: var(--warn); margin-top: 2px; text-align: right; }
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

/* Hunting: the star is a workflow action (persists to disk when the
   local dashboard server is running), not decoration -- sized and
   colored to be an obvious, deliberate click target on every row/card. */
.star-btn { border: none; background: none; cursor: pointer; font-size: 18px; line-height: 1; padding: 2px 4px; color: var(--mutedest); }
.star-btn:hover { color: var(--watch); }
.star-btn.starred { color: #d97706; }
.pill-hunting { background: #fef3c7; color: #92400e; }
.hunting-live-note { font-size: 11px; margin-top: 3px; }
.hunting-live-note.live { color: var(--buy); }
.hunting-live-note.offline { color: var(--mutedest); }
.hunting-section input[type=number], .hunting-section textarea { font: inherit; font-size: 12.5px; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; width: 100%; box-sizing: border-box; }
.hunting-section textarea { min-height: 54px; resize: vertical; }
.hunting-section .hunting-row { display: flex; gap: 10px; align-items: flex-start; margin-top: 6px; flex-wrap: wrap; }
.hunting-section .hunting-field { flex: 1 1 200px; min-width: 160px; }
.hunting-section .hunting-field label { display: block; font-size: 10.5px; text-transform: uppercase; letter-spacing: .04em; color: var(--mutedest); margin-bottom: 3px; }
.hunting-section button.save-btn { font-size: 12px; padding: 6px 12px; border: 1px solid var(--accent); color: var(--accent); background: #fff; border-radius: 6px; cursor: pointer; margin-top: 4px; }
.hunting-offer-compare { display: flex; gap: 18px; font-size: 12.5px; margin-top: 4px; }
.hunting-offer-compare div b { display: block; font-size: 15px; }
</style>
</head>
"""

_HTML_BODY_START = """<body>
<header class="topbar">
  <div class="topbar-inner">
    <div class="hello-row">
      <div>
        <div class="hello" id="hello-heading">Hello Rhys</div>
        <div class="hello-sub">Arbitrage Command Centre</div>
      </div>
      <div class="status" id="status-line">Loading...<div id="hunting-live-note" class="hunting-live-note"></div></div>
    </div>
  </div>
</header>
<main>
  <section class="command-centre" id="command-centre">
    <div class="metrics-row" id="metrics-row"></div>

    <div class="section-block">
      <div class="section-title-row">
        <h2>Top opportunities</h2>
        <span class="section-note">Best actionable items across both pipelines, ranked the same way the full list below ranks them.</span>
      </div>
      <div id="top-banner"></div>
      <div class="top-grid" id="top-grid"></div>
      <div class="section-note top-cap-note" id="top-cap-note"></div>
    </div>

    <div class="section-block">
      <div class="section-title-row">
        <h2>Browse the rest</h2>
        <span class="section-note">Click a tile to filter the full list below.</span>
      </div>
      <div class="browse-grid" id="browse-grid"></div>
      <div id="browse-categories"></div>
    </div>
  </section>

  <section class="all-opportunities">
    <div class="section-title-row">
      <h2 id="all-opportunities-heading">All opportunities</h2>
    </div>
    <div class="filters" id="filters"></div>
    <div class="sort-note">Default sort is by decision (BUY first), then each item's own pipeline score. Discovery items use a 0&ndash;100 Flip Score; Daily Scan items use a 1&ndash;10 Score &mdash; these two scores are not directly comparable, so Daily Scan items are ranked as their own group under the default sort.</div>
    <div class="queue" id="queue"></div>
  </section>
</main>
<script id="discovery-report-data" type="application/json">"""

_HTML_MID_1 = """</script>
<script id="legacy-scan-data" type="application/json">"""

_HTML_MID_2 = """</script>
<script id="bankroll-data" type="application/json">"""

_HTML_MID_3 = """</script>
<script id="hunting-state-data" type="application/json">"""

_HTML_BODY_END = """</script>
"""

_HTML_SCRIPT = r"""<script>
(function () {
  var discoveryPayload = JSON.parse(document.getElementById('discovery-report-data').textContent);
  var legacyPayload = JSON.parse(document.getElementById('legacy-scan-data').textContent);
  var bankrollCfg = JSON.parse(document.getElementById('bankroll-data').textContent);
  var huntingPayload = JSON.parse(document.getElementById('hunting-state-data').textContent);

  var discoveryOpportunities = (discoveryPayload && discoveryPayload.opportunities) || [];
  var legacyRows = (legacyPayload && legacyPayload.rows) || [];

  // ---- Hunting: user workflow state, kept entirely separate from the two
  // scanner payloads above. `huntingState` starts as the read-only
  // snapshot embedded at generation time (works even opened via file://,
  // so a star made before the last regeneration is still visible), then
  // is opportunistically replaced with a live fetch() of the same shape
  // from scanner/dashboard_server.py if that local server happens to be
  // running -- see initHuntingLive() below. Nothing here ever writes back
  // into discoveryPayload/legacyPayload.
  var huntingState = (huntingPayload && huntingPayload.hunting) || {};
  var liveMode = false;

  var PILL_CLASS = { 'BUY': 'pill-buy', 'WATCH': 'pill-watch', 'PASS': 'pill-pass', 'PROFITABLE BUT CAPITAL RISK': 'pill-risk' };
  // Sort tiers: real decisions rank by how actionable they are, unsupported
  // (unverified-source) WATCH items rank below verified ones since they were
  // never independently priced, legacy (no-decision) rows get their own
  // group ranked by their own native score, PASS is last. The Command
  // Centre's Top opportunities panel below reuses these exact tiers --
  // there is no second ranking model.
  var TIER = {
    'BUY': 0, 'PROFITABLE BUT CAPITAL RISK': 1,
    'WATCH_VERIFIED': 2, 'LEGACY': 3, 'WATCH_UNSUPPORTED': 4, 'PASS': 5
  };

  var state = {
    pipeline: 'all', decision: 'all', category: 'all', source: 'all',
    minPrice: '', maxPrice: '', minRoi: '', minConfidence: '',
    showPass: false, hideNoConfidence: false, sortBy: 'default',
    huntingOnly: false
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
  function numOrNeg(v) {
    var n = Number(v);
    return (v === null || v === undefined || v === '' || isNaN(n)) ? -Infinity : n;
  }
  function numOrPosInf(v) {
    var n = Number(v);
    return (v === null || v === undefined || v === '' || isNaN(n)) ? Infinity : n;
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
  function profitForSort(it) {
    if (it.pipeline === 'discovery') return it.raw.expected_net_profit_low;
    return it.raw.potential_profit_nzd;
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
  // Card-face confidence chip -- glanceable, next to the native score, on
  // every row and Top Opportunities card. Only Discovery items carry an
  // authoritative confidence_pct (part of the same persisted valuation
  // already shown in the detail panel); the legacy pipeline has no
  // confidence field at all. Per the "don't invent, don't placeholder"
  // rule: this renders nothing (not "Confidence: Not available") when
  // there's no real number to show, rather than a discouraging blank chip.
  function confidenceGlance(it) {
    // Unverified-source items never went through product identification/
    // valuation at all (see verification_status on scanner.models.Opportunity)
    // -- their confidence_pct is just the ResaleValuation dataclass's 0.0
    // default, not a real assessment. Showing "0% confidence" there would
    // read as "we checked and it's worthless" when the truth is "we never
    // checked" -- so this is gated on isUnsupported(it), not just on
    // whether a number is present. A *verified* item's confidence_pct can
    // legitimately be 0 (evidence was searched for and none was found)
    // and is still shown in that case, since that's a real, computed result.
    if (isUnsupported(it)) return '';
    var c = confidence(it);
    if (c === null || c === undefined || c === '') return '';
    var n = Number(c);
    if (isNaN(n)) return '';
    return '<span class="confidence-chip">' + Math.round(n) + '% confidence</span>';
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
      // Pre-existing note: this label is rendered through escapeHtml()
      // at the call site (renderRow), so it must use a literal character
      // here, not an HTML entity -- an entity would be double-escaped
      // into visible "&middot;" text.
      return { label: 'Verified listing · ' + n + ' comparable' + (n === 1 ? '' : 's'), cls: 'pill-buy' };
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

  // ---- Hunting: lookups against the separate huntingState map, keyed by
  // source + canonical URL (matching scanner.hunting_store.make_key()).
  // The discovery/legacy payloads embedded on this page are never
  // touched to add a precomputed key (see this module's own docstring),
  // so this mirrors scanner.search.util.canonicalize_url() here in JS,
  // from each row's own existing source/url fields, well enough to match
  // for the URL shapes this project's scrapers actually emit (plain
  // paths, at most a few tracking query params -- see the tracking-param
  // prefix list below, identical to the Python side's).
  //
  // This is an approximation, not a byte-identical port -- most notably,
  // Python's urlencode() and JS's encodeURIComponent() escape a handful
  // of characters (space, most visibly) differently. That could only
  // cause a false negative on whether a row is *shown* as already
  // starred; it can never affect whether starring/unstarring itself
  // works, because the server always recomputes the authoritative key
  // from the raw source/url a request sends it (see
  // scanner/dashboard_server.py), never from anything this function
  // returns.
  var _TRACKING_PARAM_PREFIXES = ['utm_', 'gclid', 'fbclid', 'ref', 'src', 'cid', 'affid'];
  function canonicalizeUrlJs(raw) {
    if (!raw) return raw || '';
    var trimmed = String(raw).trim();
    var u;
    try { u = new URL(trimmed); } catch (e) { return trimmed; }
    var netloc = u.host.toLowerCase();
    var path = u.pathname.replace(/\/+$/, '') || '/';
    var pairs = [];
    u.searchParams.forEach(function (v, k) {
      var lower = k.toLowerCase();
      var isTracking = _TRACKING_PARAM_PREFIXES.some(function (p) { return lower.indexOf(p) === 0; });
      if (!isTracking) pairs.push([k, v]);
    });
    pairs.sort(function (a, b) {
      if (a[0] !== b[0]) return a[0] < b[0] ? -1 : 1;
      if (a[1] !== b[1]) return a[1] < b[1] ? -1 : 1;
      return 0;
    });
    var query = pairs.map(function (p) { return encodeURIComponent(p[0]) + '=' + encodeURIComponent(p[1]); }).join('&');
    return 'https://' + netloc + path + (query ? '?' + query : '');
  }
  function huntingKey(it) { return (source(it) || '').trim() + '|' + canonicalizeUrlJs(url(it)); }
  function huntingEntry(it) { return huntingState[huntingKey(it)]; }
  function isHunted(it) { return !!huntingEntry(it); }
  function huntingCount() {
    var n = 0;
    items.forEach(function (it) { if (isHunted(it)) n++; });
    return n;
  }

  function postJson(path, payload) {
    return fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.error || ('HTTP ' + r.status)); });
      return r.json();
    });
  }

  function showHuntingError(msg) {
    var note = document.getElementById('hunting-live-note');
    if (!note) return;
    note.textContent = msg;
    note.className = 'hunting-live-note offline';
  }

  // Toggling the star is the one action available everywhere a row
  // appears (Top opportunities, All opportunities, Hunting filter).
  // Editing notes/target offer only happens in the expanded detail panel.
  function toggleHunting(it) {
    if (!liveMode) {
      showHuntingError('Starring needs the local dashboard server running -- see README ("python -m scanner.dashboard_server"), then reload this page.');
      return;
    }
    var already = isHunted(it);
    var body = { source: source(it), url: url(it) };
    var req = already ? postJson('/api/hunting/unstar', body) : postJson('/api/hunting/star', body);
    req.then(function (resp) {
      if (already) {
        delete huntingState[resp.key];
      } else {
        huntingState[resp.key] = resp.entry;
      }
      render();
    }).catch(function (err) {
      showHuntingError('Could not reach the local dashboard server -- is it still running? (' + err.message + ')');
    });
  }

  function saveHuntingNotes(it, notes) {
    postJson('/api/hunting/notes', { source: source(it), url: url(it), notes: notes }).then(function (resp) {
      huntingState[huntingKey(it)] = resp.entry;
      render();
    }).catch(function (err) { showHuntingError('Could not save notes: ' + err.message); });
  }

  function saveHuntingTargetOffer(it, value) {
    var n = value === '' ? null : Number(value);
    postJson('/api/hunting/target_offer', { source: source(it), url: url(it), target_offer_override: (n === null || isNaN(n)) ? null : n })
      .then(function (resp) {
        huntingState[huntingKey(it)] = resp.entry;
        render();
      }).catch(function (err) { showHuntingError('Could not save target offer: ' + err.message); });
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
      field('Sort by', selectHtml('f-sort', [
        ['default', 'Decision priority (default)'],
        ['roi', 'ROI / margin'],
        ['profit', 'Profit'],
        ['confidence', 'Confidence'],
        ['price_low', 'Price: low to high'],
        ['price_high', 'Price: high to low'],
      ], state.sortBy)) +
      '<label class="checkbox"><input type="checkbox" id="f-hide-no-confidence"' + (state.hideNoConfidence ? ' checked' : '') + '> Hide items with no confidence data</label>' +
      '<button id="toggle-pass" class="' + (state.showPass ? 'active' : '') + '">' + (state.showPass ? 'Hide passed' : 'Show passed') + '</button>' +
      '<button id="toggle-hunting" class="' + (state.huntingOnly ? 'active' : '') + '">' + (state.huntingOnly ? 'Show all' : ('★ Hunting (' + huntingCount() + ')')) + '</button>';

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
    document.getElementById('f-sort').addEventListener('change', function () { state.sortBy = this.value; render(); });
    document.getElementById('f-hide-no-confidence').addEventListener('change', function () { state.hideNoConfidence = this.checked; render(); });
    var togglePassBtn = document.getElementById('toggle-pass');
    togglePassBtn.addEventListener('click', function () {
      state.showPass = !state.showPass;
      // Update this button's own label/state in place rather than going
      // through renderFilters() -- renderFilters() rebuilds every filter
      // control's DOM node, which would steal focus from whichever field
      // the user is in the middle of using (see render()'s comment below).
      this.className = state.showPass ? 'active' : '';
      this.textContent = state.showPass ? 'Hide passed' : 'Show passed';
      render();
    });
    var toggleHuntingBtn = document.getElementById('toggle-hunting');
    toggleHuntingBtn.addEventListener('click', function () {
      state.huntingOnly = !state.huntingOnly;
      this.className = state.huntingOnly ? 'active' : '';
      this.textContent = state.huntingOnly ? 'Show all' : ('★ Hunting (' + huntingCount() + ')');
      render();
    });
  }

  // Called after every star/unstar so the toggle button's live count
  // stays correct even when the click that changed it happened on a row
  // (not on this button) -- mirrors how togglePassBtn updates its own
  // label in place above, without going through renderFilters().
  function refreshHuntingToggleLabel() {
    var btn = document.getElementById('toggle-hunting');
    if (!btn) return;
    btn.textContent = state.huntingOnly ? 'Show all' : ('★ Hunting (' + huntingCount() + ')');
  }

  // The dark header stays deliberately minimal -- just enough to say
  // "is this data fresh". The BUY/WATCH/PASS/etc counts this used to
  // repeat here now live in exactly one place, the metric tiles below,
  // so "Hello Rhys" stays the header's clear visual anchor instead of
  // competing with a dense counts paragraph.
  function renderStatus() {
    var discTs = discoveryPayload && discoveryPayload.run_timestamp ? new Date(discoveryPayload.run_timestamp).toLocaleString() : 'no discovery run yet';
    var legTs = legacyPayload && legacyPayload.run_timestamp ? new Date(legacyPayload.run_timestamp).toLocaleString() : 'no daily scan run yet';
    var html =
      '<div class="status-row">Discovery updated <b>' + discTs + '</b></div>' +
      '<div class="status-row">Daily scan updated <b>' + legTs + '</b></div>' +
      '<div id="hunting-live-note" class="hunting-live-note"></div>';
    document.getElementById('status-line').innerHTML = html;
    refreshHuntingLiveNote();
  }

  // Tells Rhys, plainly, whether clicking a star right now will actually
  // persist anywhere -- the embedded snapshot alone (no local server
  // running) is read-only, and a click doing nothing with no explanation
  // would look like a bug rather than a known, documented limitation.
  function refreshHuntingLiveNote() {
    var note = document.getElementById('hunting-live-note');
    if (!note) return;
    if (liveMode) {
      note.textContent = 'Hunting: live -- stars save to disk';
      note.className = 'hunting-live-note live';
    } else {
      note.textContent = 'Hunting: read-only snapshot -- run "python -m scanner.dashboard_server" to enable starring';
      note.className = 'hunting-live-note offline';
    }
  }
  function isUnsupportedRaw(o) { return o.verification_status && o.verification_status !== 'verified'; }

  // ---- Command Centre: summary metrics -- pure re-presentation of
  // decision_counts/row counts that are already embedded above, plus the
  // two static bankroll reference figures. No new computation. ----
  function metricTile(label, value, cls, note) {
    return '<div class="metric-tile">' +
      '<div class="metric-value' + (cls ? ' ' + cls : '') + '">' + escapeHtml(String(value)) + '</div>' +
      '<div class="metric-label">' + escapeHtml(label) + '</div>' +
      (note ? '<div class="metric-note">' + escapeHtml(note) + '</div>' : '') +
      '</div>';
  }
  function renderMetrics() {
    var counts = (discoveryPayload && discoveryPayload.decision_counts) || {};
    var buy = counts['BUY'] || 0;
    var risk = counts['PROFITABLE BUT CAPITAL RISK'] || 0;
    var watch = counts['WATCH'] || 0;
    var pass = counts['PASS'] || 0;
    var watchVerified = discoveryOpportunities.filter(function (o) { return o.decision === 'WATCH' && !isUnsupportedRaw(o); }).length;
    var watchUnsupported = discoveryOpportunities.filter(function (o) { return o.decision === 'WATCH' && isUnsupportedRaw(o); }).length;

    var tiles = [];
    tiles.push(metricTile('BUY', buy, 'metric-value-buy'));
    tiles.push(metricTile('WATCH', watch, 'metric-value-watch', watch ? (watchVerified + ' verified · ' + watchUnsupported + ' unverified-source') : ''));
    if (risk) tiles.push(metricTile('CAPITAL RISK', risk, 'metric-value-risk'));
    tiles.push(metricTile('PASS', pass, 'metric-value-pass'));
    tiles.push(metricTile('DAILY SCAN ITEMS', legacyRows.length, 'metric-value-legacy', 'no BUY/WATCH decision — scored 1–10'));
    if (bankrollCfg && (bankrollCfg.starting_bankroll !== null && bankrollCfg.starting_bankroll !== undefined || bankrollCfg.target_bankroll !== null && bankrollCfg.target_bankroll !== undefined)) {
      tiles.push(metricTile(
        'BANKROLL',
        money(bankrollCfg.starting_bankroll) + ' → ' + money(bankrollCfg.target_bankroll),
        '',
        'starting → target · not live capital tracking'
      ));
    }
    document.getElementById('metrics-row').innerHTML = tiles.join('') +
      '<div class="metric-caveat">New/recently-listed counts aren&rsquo;t part of today&rsquo;s persisted report, so they aren&rsquo;t shown here.</div>';
  }

  // ---- Command Centre: Top opportunities -- exactly the same tier +
  // native-score ranking the full list below uses (sortTier /
  // nativeScoreForSort). No second scoring/valuation model.
  //
  // Curation rule (conservative, on purpose): every BUY / CAPITAL RISK /
  // verified-WATCH item is decision-graded -- it went through the real
  // gate -- so all of it is shown (capped only at MAX_TOP_PICKS as a
  // sanity ceiling, not a target to fill). Daily-scan (legacy) items
  // never went through that gate at all -- they're a plain 1-10 AI
  // score with no BUY/WATCH/PASS logic behind it -- so they are never
  // used as filler to pad the panel out to a round number. At most
  // LEGACY_TOP_FILL_CAP of the strongest ones are added for context, and
  // only after every decision-graded item is already included. If there
  // aren't enough genuinely-ranked items to fill the panel, the panel is
  // simply smaller -- it never reaches for weaker results to look fuller
  // than the data supports. Nothing is ever hidden from the full list
  // below; this only controls what's *additionally* highlighted here.
  var MAX_TOP_PICKS = 10;
  var LEGACY_TOP_FILL_CAP = 3;

  function byTierThenScore(a, b) {
    var ta = sortTier(a), tb = sortTier(b);
    if (ta !== tb) return ta - tb;
    return nativeScoreForSort(b) - nativeScoreForSort(a);
  }
  function computeTopPicks() {
    var decisionGraded = items.filter(function (it) {
      var t = sortTier(it);
      return t === TIER.BUY || t === TIER['PROFITABLE BUT CAPITAL RISK'] || t === TIER.WATCH_VERIFIED;
    }).sort(byTierThenScore);
    var legacyRanked = items.filter(function (it) { return sortTier(it) === TIER.LEGACY; }).sort(byTierThenScore);

    var picks = decisionGraded.slice(0, MAX_TOP_PICKS);
    var legacyFillCount = Math.min(LEGACY_TOP_FILL_CAP, Math.max(0, MAX_TOP_PICKS - picks.length), legacyRanked.length);
    picks = picks.concat(legacyRanked.slice(0, legacyFillCount));
    return { picks: picks, legacyShown: legacyFillCount, legacyTotal: legacyRanked.length };
  }
  function renderTopOpportunities() {
    var buyCount = items.filter(function (it) { return sortTier(it) === TIER.BUY; }).length;
    var result = computeTopPicks();
    var picks = result.picks;
    var banner = document.getElementById('top-banner');
    var grid = document.getElementById('top-grid');

    if (buyCount === 0) {
      banner.innerHTML = '<div class="no-buy-banner">No BUY-tier opportunities right now &mdash; nothing here should be treated as a buy. The cards below are the strongest WATCH / daily-scan candidates in the latest data, shown with their real WATCH / no-decision status.</div>';
    } else {
      banner.innerHTML = '<div class="all-buy-banner">' + buyCount + ' BUY-tier opportunit' + (buyCount === 1 ? 'y' : 'ies') + ' in the latest data.</div>';
    }

    grid.innerHTML = '';
    if (!picks.length) {
      var empty = document.createElement('div');
      empty.className = 'empty-run';
      empty.textContent = 'Nothing in the latest data clears even a verified WATCH / daily-scan bar right now.';
      grid.appendChild(empty);
      var note = document.getElementById('top-cap-note');
      if (note) note.textContent = '';
      return;
    }
    picks.forEach(function (it) {
      var card = renderRow(it);
      card.classList.add('top-card');
      var d = decision(it);
      if (d === 'BUY') card.classList.add('top-card-buy');
      else if (d === 'PROFITABLE BUT CAPITAL RISK') card.classList.add('top-card-risk');
      else if (d === 'WATCH') card.classList.add('top-card-watch');
      else if (it.pipeline === 'legacy') card.classList.add('top-card-legacy');
      grid.appendChild(card);
    });

    var note = document.getElementById('top-cap-note');
    if (note) {
      note.textContent = result.legacyTotal > result.legacyShown
        ? 'Showing every BUY / capital-risk / verified-WATCH item, plus the ' + result.legacyShown + ' strongest of ' + result.legacyTotal + ' daily-scan items (a plain 1–10 score with no BUY/WATCH gate behind it) — not padded further just to fill the panel. Nothing is hidden: the rest are in All opportunities below.'
        : '';
    }
  }

  // ---- Command Centre: browse-the-rest breakdown. Grouped by "source"
  // (Turners/Thorntons/Mainland/...), the one field both pipelines
  // genuinely persist -- Discovery opportunities have no "category"
  // field at all (see the discovery detail's own missing-note below), so
  // grouping by category for every item would fabricate a dimension that
  // doesn't exist for most of the data. Category tiles are still offered
  // as a second, clearly-labelled breakdown for the Daily Scan items that
  // do have one. Clicking a tile reuses the existing category/source
  // filter state -- no new filtering logic. ----
  function renderBrowseBreakdown() {
    var counts = {};
    items.forEach(function (it) {
      var key = source(it);
      counts[key] = (counts[key] || 0) + 1;
    });
    var keys = Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; });
    var grid = document.getElementById('browse-grid');
    grid.innerHTML = keys.length ? keys.map(function (key) {
      return '<button type="button" class="browse-tile" data-source="' + escapeAttr(key) + '">' +
        '<div class="browse-count">' + counts[key] + '</div>' +
        '<div class="browse-label">' + escapeHtml(key) + '</div>' +
        '</button>';
    }).join('') : '<div class="empty-note">No sources recorded yet.</div>';

    Array.prototype.forEach.call(grid.querySelectorAll('.browse-tile'), function (btn) {
      btn.addEventListener('click', function () {
        state.source = btn.getAttribute('data-source');
        var sel = document.getElementById('f-source');
        if (sel) sel.value = state.source;
        render();
        var heading = document.getElementById('all-opportunities-heading');
        if (heading) heading.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    });

    var catWrap = document.getElementById('browse-categories');
    if (categories.length) {
      var catCounts = {};
      items.forEach(function (it) { var c = category(it); if (c) catCounts[c] = (catCounts[c] || 0) + 1; });
      catWrap.innerHTML = '<div class="browse-subhead">Daily-scan categories</div><div class="browse-pills">' +
        categories.map(function (c) {
          return '<button type="button" class="browse-pill" data-category="' + escapeAttr(c) + '">' + escapeHtml(c) + '<span>' + (catCounts[c] || 0) + '</span></button>';
        }).join('') + '</div>';
      Array.prototype.forEach.call(catWrap.querySelectorAll('.browse-pill'), function (btn) {
        btn.addEventListener('click', function () {
          state.category = btn.getAttribute('data-category');
          var sel = document.getElementById('f-category');
          if (sel) sel.value = state.category;
          render();
          var heading = document.getElementById('all-opportunities-heading');
          if (heading) heading.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
      });
    } else {
      catWrap.innerHTML = '';
    }
  }

  function passFilters(it) {
    if (state.huntingOnly && !isHunted(it)) return false;
    if (state.pipeline !== 'all' && it.pipeline !== state.pipeline) return false;
    // "Show passed" hides PASS items from mixed views (All/other-decision)
    // by default, since they've already been rejected -- but explicitly
    // selecting Decision = PASS is an unambiguous request to see them, so
    // it must not also require toggling the separate "Show passed"
    // control the user has no reason to know about.
    if (!state.showPass && state.decision !== 'PASS' && sortTier(it) === TIER.PASS) return false;
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

  function sortComparator(a, b) {
    if (state.sortBy === 'roi') return numOrNeg(roiForFilter(b)) - numOrNeg(roiForFilter(a));
    if (state.sortBy === 'profit') return numOrNeg(profitForSort(b)) - numOrNeg(profitForSort(a));
    if (state.sortBy === 'confidence') return numOrNeg(confidence(b)) - numOrNeg(confidence(a));
    if (state.sortBy === 'price_low') return numOrPosInf(price(a)) - numOrPosInf(price(b));
    if (state.sortBy === 'price_high') return numOrNeg(price(b)) - numOrNeg(price(a));
    var ta = sortTier(a), tb = sortTier(b);
    if (ta !== tb) return ta - tb;
    return nativeScoreForSort(b) - nativeScoreForSort(a);
  }

  function sortedItems() {
    var list = items.filter(passFilters);
    list.sort(sortComparator);
    return list;
  }

  function evidenceTag(type) {
    var cls = type === 'SOLD' ? 'evidence-badge sold' : 'evidence-badge';
    return '<span class="' + cls + '">' + (type || 'OTHER').replace('_', ' ').toLowerCase() + '</span>';
  }

  // Shared by both detail renderers below. Deliberately its own labeled
  // section, visually and structurally separate from the scanner-authored
  // sections around it -- this is the one place user-authored workflow
  // state (huntingState) is shown, and it must never be confused with
  // scanner output. Explicitly puts "Scanner max buy" and "Your target
  // offer" side by side so the two numbers -- one computed, one the
  // user's own -- can never be mistaken for each other.
  function renderHuntingSection(it) {
    var hunted = isHunted(it);
    var entry = huntingEntry(it) || {};
    var hasOverride = entry.target_offer_override !== null && entry.target_offer_override !== undefined;
    var scannerMaxBuy = it.pipeline === 'discovery' ? money(it.raw.max_buy_price) : 'Not available (legacy pipeline has no max buy price)';

    var statusLine = hunted
      ? 'Hunting since ' + (entry.starred_at ? new Date(entry.starred_at).toLocaleString() : 'unknown time')
      : 'Not currently hunting -- click the star above to start tracking this opportunity.';

    var compare = '<div class="hunting-offer-compare">' +
      '<div>Scanner max buy<b>' + scannerMaxBuy + '</b></div>' +
      '<div>Your target offer<b>' + (hasOverride ? money(entry.target_offer_override) : 'Not set') + '</b></div>' +
      '</div>';

    var editRows = hunted
      ? '<div class="hunting-row">' +
        '<div class="hunting-field"><label>Your target offer ($, optional &mdash; your own number, separate from the scanner max buy above)</label>' +
        '<input type="number" class="target-offer-input" value="' + (hasOverride ? entry.target_offer_override : '') + '"></div>' +
        '<div class="hunting-field"><label>Notes</label><textarea class="notes-input">' + escapeHtml(entry.notes || '') + '</textarea></div>' +
        '</div>' +
        '<button type="button" class="save-btn">Save notes / target offer</button>'
      : '';

    return '<div class="sechead">Hunting (your workflow state &mdash; kept separate from scanner data)</div>' +
      '<div class="hunting-section">' +
      '<div style="font-size:13px;">' + escapeHtml(statusLine) + '</div>' +
      compare +
      editRows +
      '</div>';
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
      renderHuntingSection(it) +
      '<div class="missing-note">Condition, listing location, image, and seller status are not currently part of the discovery pipeline&rsquo;s persisted output for this item.</div>' +
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
      renderHuntingSection(it) +
      '<div class="missing-note">Flip score, valuation confidence, ROI range, liquidity classification, max buy price, and structured comparable evidence are not part of the legacy daily-scan pipeline&rsquo;s persisted output &mdash; this item was scored 1&ndash;10 by a separate, older code path. Reserve status and closing time exist only as free text inside "notes", not as separate fields.</div>' +
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
    var hunted = isHunted(it);
    var starTitle = hunted ? 'Stop hunting (unstar)' : 'Star: keep tracking this opportunity';
    var starBtn = '<button type="button" class="star-btn' + (hunted ? ' starred' : '') + '" title="' + starTitle + '" aria-label="' + starTitle + '">' + (hunted ? '★' : '☆') + '</button>';
    var huntingPill = hunted ? '<span class="pill pill-hunting">HUNTING</span>' : '';

    var rowHtml =
      '<div class="row-main">' +
      '<div class="row-left">' +
      '<div class="row-head">' + starBtn + pipelineTag + decisionPill + unsupportedPill + huntingPill +
      '<span class="score">' + nativeScoreLine(it) + '</span>' +
      confidenceGlance(it) +
      '</div>' +
      '<div class="title">' + escapeHtml(title(it)) + '</div>' +
      '<div class="source">' + escapeHtml(source(it)) + (category(it) ? ' &middot; ' + escapeHtml(category(it)) : '') + ' &middot; ' + escapeHtml(eq.label) + '</div>' +
      '</div>' +
      '<div class="row-right">' +
      '<div class="price-line">' +
      '<span class="price-block"><span class="price-figure">' + money(price(it)) + '</span><span class="price-label">Asking</span></span>' +
      '<span class="arrow">&rarr;</span>' +
      '<span class="price-block"><span class="price-figure">' + maxBuy + '</span><span class="price-label">Max buy</span></span>' +
      '</div>' +
      liveBidFlag +
      '<div class="profit-line">Profit ' + estProfitLine(it) + '</div>' +
      '<div class="roi-line">ROI/margin ' + roiLine(it) + '</div>' +
      noEvidenceFlag +
      '</div>' +
      '</div>';

    var row = document.createElement('div');
    row.className = 'row';
    row.dataset.key = it.key;
    row.innerHTML = rowHtml;
    var starEl = row.querySelector('.star-btn');
    if (starEl) {
      starEl.addEventListener('click', function (e) {
        e.stopPropagation();
        toggleHunting(it);
      });
    }
    row.addEventListener('click', function (e) {
      if (e.target.closest('a')) return;
      if (e.target.closest('.star-btn')) return;
      expandedKey = (expandedKey === it.key) ? null : it.key;
      render();
    });

    if (expandedKey === it.key) {
      var detailWrap = document.createElement('div');
      detailWrap.innerHTML = it.pipeline === 'discovery' ? renderDiscoveryDetail(it) : renderLegacyDetail(it);
      detailWrap.firstChild.addEventListener('click', function (e) { e.stopPropagation(); });
      var saveBtn = detailWrap.firstChild.querySelector('.hunting-section .save-btn');
      if (saveBtn) {
        saveBtn.addEventListener('click', function () {
          var section = saveBtn.closest('.hunting-section');
          var notesVal = section.querySelector('.notes-input').value;
          var offerVal = section.querySelector('.target-offer-input').value;
          saveHuntingNotes(it, notesVal);
          saveHuntingTargetOffer(it, offerVal);
        });
      }
      row.appendChild(detailWrap.firstChild);
    }
    return row;
  }

  // render() redraws the Top Opportunities panel and the results queue.
  // It deliberately does NOT call renderFilters() -- renderFilters()
  // replaces every filter control's DOM node via innerHTML, which would
  // steal focus from whichever free-text filter field (Min price, Max
  // price, Min ROI/profit %, Min confidence %) the user is in the middle
  // of typing into, silently swallowing the rest of the keystroke (e.g.
  // "500" would only ever register as "5"). renderFilters() is called
  // exactly once, below, to build the controls and wire their listeners;
  // after that, each control keeps its own DOM node and its own native
  // input/selection state for the rest of the page's life. The Top
  // Opportunities panel and the queue below contain no text inputs, so
  // rebuilding them on every keystroke (needed because the numeric
  // filters affect what "actionable"/matching means) is safe. The one
  // exception (the "Show passed" button's label) updates itself directly
  // in its own click handler above. renderMetrics() and
  // renderBrowseBreakdown() are also called once, below -- their counts
  // are global tallies independent of the filter state, not filtered
  // views, so they don't need to re-render on every keystroke either.
  function render() {
    renderTopOpportunities();
    refreshHuntingToggleLabel();
    refreshHuntingLiveNote();

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
  renderMetrics();
  renderBrowseBreakdown();
  renderFilters();
  render();

  // Upgrade from the embedded read-only Hunting snapshot to live state if
  // scanner/dashboard_server.py happens to be serving this page right now
  // (same-origin fetch succeeds only in that case -- opened via file://,
  // or via this same server with no listener, it fails fast and this page
  // simply stays on the embedded snapshot). Deliberately does not block
  // the first paint above: the snapshot renders immediately, then this
  // silently re-renders once if it upgrades to live.
  fetch('/api/hunting', { cache: 'no-store' }).then(function (r) {
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }).then(function (data) {
    liveMode = true;
    huntingState = (data && data.hunting) || {};
    render();
  }).catch(function () {
    liveMode = false;
    refreshHuntingLiveNote();
  });
})();
</script>
"""

_HTML_FOOT = """</body>
</html>
"""
