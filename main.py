"""
NZ Auction Opportunity Scanner
==============================
Two pipelines, run per category:

1. TURNERS (real value scoring): scrapes Turners' server-rendered catalog
   pages for real prices, groups similar items (e.g. multiple "18V Drill"
   listings), fetches condition data, and has Claude score each item's
   value relative to its group peers -- genuine price+condition comparison.

2. THORNTONS / MAINLAND AUCTIONS (blurb scoring): these platforms only
   expose per-item price/condition via JavaScript-loaded live bidding,
   which isn't reliably scrapeable (see README). So these are scored on
   auction-EVENT listing language only ("unreserved," "liquidation," etc)
   -- a much weaker signal, clearly labelled as such in the report.

Usage:
    python main.py                 # normal run: only NEW listings since last run
    python main.py --rescan        # ignore the "seen" cache, report everything found

This does NOT run continuously in the background. To get "regular" scans,
schedule it -- see README.md for GitHub Actions or Windows Task Scheduler.
"""
import argparse
import json
import os
import time

from scanner.scrapers import SCRAPERS
from scanner.scrapers.turners_catalog import fetch_all_categories as fetch_turners_category
from scanner.matcher import match_categories, primary_category
from scanner.trademe_links import trademe_search_url
from scanner.facebook import marketplace_search_url
from scanner.ebay_links import ebay_sold_search_url
from scanner.ai_opportunity import analyze_listing
from scanner.ai_value import score_group
from scanner.grouping import group_similar_items
from scanner.item_detail import fetch_item_detail
from scanner.store import load_seen, save_seen
from scanner.report import write_report
from scanner.notifier import send_telegram_message, build_summary

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    # Secrets can come from environment variables (e.g. GitHub Actions
    # secrets) and override whatever's in config.json -- this lets you keep
    # config.json free of real keys if you push this to a repo.
    config["anthropic_api_key"] = os.environ.get("ANTHROPIC_API_KEY", config.get("anthropic_api_key", ""))
    config["telegram_bot_token"] = os.environ.get("TELEGRAM_BOT_TOKEN", config.get("telegram_bot_token", ""))
    config["telegram_chat_id"] = os.environ.get("TELEGRAM_CHAT_ID", config.get("telegram_chat_id", ""))
    return config


def _search_links(term: str) -> dict:
    return {
        "trademe_search_url": trademe_search_url(term),
        "facebook_search_url": marketplace_search_url(term),
        "ebay_search_url": ebay_sold_search_url(term),
    }


def run_turners_pipeline(category: str, config: dict, seen: set, new_seen: set) -> list:
    """Real price+condition value scoring for a category, via Turners'
    server-rendered catalog. Only items that group with 2+ similar peers
    get scored (comparison needs something to compare against); singletons
    are skipped rather than reported with no basis for a value judgement."""
    rows = []
    user_agent = config.get("user_agent", "NZ-Reseller-Scanner/1.0")
    delay = config.get("request_delay_seconds", 2.0)

    items = fetch_turners_category(category, user_agent, request_delay=delay)
    print(f"[main]   Turners catalog '{category}': found {len(items)} item(s)")
    if not items:
        return rows

    min_group_size = config.get("min_group_size", 2)
    similarity_threshold = config.get("similarity_threshold", 0.4)
    groups = group_similar_items(items, min_group_size=min_group_size, similarity_threshold=similarity_threshold)
    print(f"[main]   Turners catalog '{category}': {len(groups)} comparable group(s)")

    for group in groups:
        # Fetch condition/description for every item in the group (needed
        # for a fair comparison), even ones already seen in a prior run.
        for item in group:
            detail = fetch_item_detail(item["url"], user_agent)
            item.update(detail)
            time.sleep(delay)

        ai_results = score_group(group, config.get("anthropic_api_key", ""))

        for item, ai_result in zip(group, ai_results):
            new_seen.add(item["url"])
            if item["url"] in seen:
                continue  # already reported in a previous run

            price = item.get("price")
            new_price = ai_result.get("estimated_new_price_nzd")
            value_vs_new_pct = ""
            if price and new_price and new_price > 0:
                value_vs_new_pct = round((1 - (price / new_price)) * 100)

            search_term = item["title"]
            rows.append({
                "category": category,
                "source": "Turners",
                "data_basis": "Real price + condition",
                "title": item["title"],
                "url": item["url"],
                "price_nzd": price if price is not None else "",
                "condition": item.get("condition", ""),
                "score": ai_result.get("score"),
                "reasons": "; ".join(ai_result.get("reasons", [])),
                "estimated_new_price_nzd": new_price if new_price is not None else "",
                "value_vs_new_pct": value_vs_new_pct,
                **_search_links(search_term),
                "notes": f"Reserve: {item.get('reserve_status', 'unknown')}; Closes {item.get('closing_date', 'unknown')}",
            })

    return rows


def run_blurb_pipeline(config: dict, seen: set, new_seen: set) -> list:
    """Auction-event-level scoring for Thorntons / Mainland Auctions, based
    only on listing language -- no real price or condition data available."""
    rows = []
    user_agent = config.get("user_agent", "NZ-Reseller-Scanner/1.0")
    watch_categories = config.get("watch_categories", {})
    category_order = list(watch_categories.keys())

    all_listings = []
    for site_name, enabled in config.get("sites", {}).items():
        if not enabled:
            continue
        fetch_fn = SCRAPERS.get(site_name)
        if not fetch_fn:
            print(f"[main] no scraper registered for '{site_name}', skipping")
            continue
        print(f"[main] scanning {site_name}...")
        listings = fetch_fn(user_agent)
        print(f"[main]   found {len(listings)} listing(s)")
        all_listings.extend(listings)

    for listing in all_listings:
        url = listing["url"]
        if url in seen:
            continue
        new_seen.add(url)

        text = f"{listing['title']} {listing.get('description', '')}"
        matches = match_categories(text, watch_categories)
        if not matches:
            continue

        category = primary_category(matches, category_order)
        matched_keywords = matches[category]
        other_categories = [c for c in matches if c != category]
        search_term = matched_keywords[0]

        ai_result = analyze_listing(listing["title"], listing.get("description", ""), config.get("anthropic_api_key", ""))

        notes = []
        if other_categories:
            notes.append(f"Also matches: {', '.join(other_categories)}")
        if ai_result["flags"]:
            notes.append("Caution: " + "; ".join(ai_result["flags"]))

        rows.append({
            "category": category,
            "source": listing["source"],
            "data_basis": "Listing language only (no price data)",
            "title": listing["title"],
            "url": url,
            "price_nzd": "",
            "condition": "",
            "score": ai_result.get("score"),
            "reasons": "; ".join(ai_result.get("reasons", [])),
            "estimated_new_price_nzd": "",
            "value_vs_new_pct": "",
            **_search_links(search_term),
            "notes": "; ".join(notes),
        })

    return rows


def main():
    parser = argparse.ArgumentParser(description="NZ auction opportunity scanner")
    parser.add_argument("--rescan", action="store_true", help="Ignore seen-cache, report all matches")
    args = parser.parse_args()

    config = load_config()
    seen = set() if args.rescan else load_seen()
    new_seen = set(seen)

    all_rows = []

    turners_categories = config.get("turners_categories", [])
    for category in turners_categories:
        print(f"[main] scanning Turners catalog for '{category}'...")
        all_rows.extend(run_turners_pipeline(category, config, seen, new_seen))

    all_rows.extend(run_blurb_pipeline(config, seen, new_seen))

    save_seen(new_seen)

    if not all_rows:
        print("[main] no new matching listings this run.")
        return

    # Cap to the top N per category (highest score first, unscored last)
    max_per_category = config.get("max_items_per_category", 3)
    by_category = {}
    for row in all_rows:
        by_category.setdefault(row["category"], []).append(row)

    capped_rows = []
    for category, rows in by_category.items():
        rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0)))
        capped_rows.extend(rows[:max_per_category])

    path = write_report(capped_rows)
    print(f"[main] wrote {len(capped_rows)} opportunity row(s) to {path}")

    summary = build_summary(capped_rows)
    sent = send_telegram_message(
        config.get("telegram_bot_token", ""),
        config.get("telegram_chat_id", ""),
        summary,
    )
    if sent:
        print("[main] Telegram notification sent.")
    elif config.get("telegram_bot_token") or config.get("telegram_chat_id"):
        print("[main] Telegram notification failed -- check bot token / chat ID.")


if __name__ == "__main__":
    main()
