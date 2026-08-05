"""
NZ Auction Opportunity Scanner
==============================
Two pipelines, run per category:

1. TURNERS (real value scoring): scrapes Turners' server-rendered catalog
   and vehicle-division pages for real prices, groups similar items (e.g.
   multiple "18V Drill" listings), fetches condition data, and has Claude
   score each item's value relative to its group peers -- genuine
   price+condition comparison. If a category doesn't have enough similar
   items to compare, it still surfaces the cheapest ungrouped items
   (clearly flagged as "no direct comparable found") so every category
   gets a fair shot at hitting the minimum-per-category target.

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
from scanner.scrapers.turners_vehicles import fetch_all_divisions as fetch_turners_vehicles
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

# Turners categories that are vehicle divisions (different scraper/template
# than the General Goods catalog) -- see scanner/scrapers/turners_vehicles.py
VEHICLE_CATEGORIES = {"Cars", "Trucks & Machinery", "Motorbikes", "Trailers & Caravans"}


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

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


def _build_row(category: str, item: dict, ai_result: dict, notes_extra: str = "") -> dict:
    price = item.get("price")
    buy_now = item.get("buy_now_price")
    new_price = ai_result.get("estimated_new_price_nzd")
    value_vs_new_pct = ""
    if price and new_price and new_price > 0:
        value_vs_new_pct = round((1 - (price / new_price)) * 100)

    search_term = item["title"]
    notes = notes_extra
    reserve = item.get("reserve_status") or "unknown"
    closes = item.get("closing_date") or "unknown"
    extra_note = f"Reserve: {reserve}; Closes {closes}" if reserve != "unknown" or closes != "unknown" else ""
    if extra_note:
        notes = f"{notes}; {extra_note}" if notes else extra_note

    return {
        "category": category,
        "source": "Turners",
        "data_basis": "Real price + condition",
        "title": item["title"],
        "url": item["url"],
        "price_nzd": price if price is not None else "",
        "buy_now_price_nzd": buy_now if buy_now is not None else "",
        "condition": item.get("condition", ""),
        "score": ai_result.get("score"),
        "reasons": "; ".join(ai_result.get("reasons", [])),
        "explanation": ai_result.get("explanation", ""),
        "estimated_new_price_nzd": new_price if new_price is not None else "",
        "value_vs_new_pct": value_vs_new_pct,
        **_search_links(search_term),
        "notes": notes,
    }


def run_turners_pipeline(category: str, config: dict, seen: set, new_seen: set) -> list:
    rows = []
    user_agent = config.get("user_agent", "NZ-Reseller-Scanner/1.0")
    delay = config.get("request_delay_seconds", 2.0)
    min_items = config.get("min_items_per_category", 2)

    if category in VEHICLE_CATEGORIES:
        items = fetch_turners_vehicles([category], user_agent, request_delay=delay)
    else:
        items = fetch_turners_category(category, user_agent, request_delay=delay)
    print(f"[main]   Turners '{category}': found {len(items)} item(s)")
    if not items:
        return rows

    min_group_size = config.get("min_group_size", 2)
    similarity_threshold = config.get("similarity_threshold", 0.35)
    groups = group_similar_items(items, min_group_size=min_group_size, similarity_threshold=similarity_threshold)
    print(f"[main]   Turners '{category}': {len(groups)} comparable group(s)")

    grouped_item_ids = set()
    new_row_count = 0

    for group in groups:
        for item in group:
            detail = fetch_item_detail(item["url"], user_agent)
            item.update(detail)
            time.sleep(delay)
            grouped_item_ids.add(item["item_id"])

        ai_results = score_group(group, config.get("anthropic_api_key", ""))

        for item, ai_result in zip(group, ai_results):
            new_seen.add(item["url"])
            if item["url"] in seen:
                continue
            rows.append(_build_row(category, item, ai_result))
            new_row_count += 1

    # Backfill: if this category didn't hit the minimum via grouped
    # comparisons, pull in the cheapest ungrouped (singleton) items too --
    # scored individually against general knowledge rather than group
    # peers, clearly flagged as such.
    if new_row_count < min_items:
        ungrouped = [i for i in items if i["item_id"] not in grouped_item_ids and i["url"] not in seen]
        ungrouped_with_price = [i for i in ungrouped if i.get("price") or i.get("buy_now_price")]
        ungrouped_with_price.sort(key=lambda i: (i.get("price") or i.get("buy_now_price") or 0))
        needed = min_items - new_row_count

        for item in ungrouped_with_price[:needed]:
            detail = fetch_item_detail(item["url"], user_agent)
            item.update(detail)
            time.sleep(delay)
            ai_result = score_group([item], config.get("anthropic_api_key", ""))[0]
            new_seen.add(item["url"])
            rows.append(_build_row(category, item, ai_result, notes_extra="No comparable item found this run -- standalone assessment only"))

    return rows


def run_blurb_pipeline(config: dict, seen: set, new_seen: set) -> list:
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
            "buy_now_price_nzd": "",
            "condition": "",
            "score": ai_result.get("score"),
            "reasons": "; ".join(ai_result.get("reasons", [])),
            "explanation": ai_result.get("explanation", ""),
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
        print(f"[main] scanning Turners for '{category}'...")
        all_rows.extend(run_turners_pipeline(category, config, seen, new_seen))

    all_rows.extend(run_blurb_pipeline(config, seen, new_seen))

    save_seen(new_seen)

    if not all_rows:
        print("[main] no new matching listings this run.")
        return

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
