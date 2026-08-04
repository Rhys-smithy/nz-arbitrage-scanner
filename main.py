"""
NZ Auction Opportunity Scanner
==============================
Scans configured NZ auction sites for new listings, matches them against
your watch-keywords, pulls Trade Me comparable pricing where possible, and
writes a CSV report of what's worth a closer look.

Usage:
    python main.py                 # normal run: only NEW listings since last run
    python main.py --rescan        # ignore the "seen" cache, report everything found
    python main.py --dry-run       # scrape + match only, skip Trade Me API calls

This does NOT run continuously in the background. To get "regular" scans,
schedule it -- see README.md for a Windows Task Scheduler example.
"""
import argparse
import json
import os

from scanner.scrapers import SCRAPERS
from scanner.matcher import match_categories, primary_category
from scanner.trademe_api import TradeMeClient
from scanner.facebook import marketplace_search_url
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
    config["trademe_api_key"] = os.environ.get("TRADEME_API_KEY", config.get("trademe_api_key", ""))
    config["telegram_bot_token"] = os.environ.get("TELEGRAM_BOT_TOKEN", config.get("telegram_bot_token", ""))
    config["telegram_chat_id"] = os.environ.get("TELEGRAM_CHAT_ID", config.get("telegram_chat_id", ""))
    return config


def main():
    parser = argparse.ArgumentParser(description="NZ auction opportunity scanner")
    parser.add_argument("--rescan", action="store_true", help="Ignore seen-cache, report all matches")
    parser.add_argument("--dry-run", action="store_true", help="Skip Trade Me API calls (faster, for testing scrapers)")
    args = parser.parse_args()

    config = load_config()
    seen = set() if args.rescan else load_seen()

    trademe = TradeMeClient(
        consumer_key=config.get("trademe_api_key", ""),
        user_agent=config.get("user_agent", "NZ-Reseller-Scanner/1.0"),
        request_delay=config.get("request_delay_seconds", 2.0),
    )

    all_listings = []
    for site_name, enabled in config.get("sites", {}).items():
        if not enabled:
            continue
        fetch_fn = SCRAPERS.get(site_name)
        if not fetch_fn:
            print(f"[main] no scraper registered for '{site_name}', skipping")
            continue
        print(f"[main] scanning {site_name}...")
        listings = fetch_fn(config.get("user_agent", "NZ-Reseller-Scanner/1.0"))
        print(f"[main]   found {len(listings)} listing(s)")
        all_listings.extend(listings)

    watch_categories = config.get("watch_categories", {})
    category_order = list(watch_categories.keys())
    min_comparables = config.get("min_trademe_comparables", 3)

    report_rows = []
    new_seen = set(seen)

    for listing in all_listings:
        url = listing["url"]
        if url in seen:
            continue  # already flagged in a previous run
        new_seen.add(url)

        text = f"{listing['title']} {listing.get('description', '')}"
        matches = match_categories(text, watch_categories)
        if not matches:
            continue  # doesn't touch any category you're watching

        category = primary_category(matches, category_order)
        matched_keywords = matches[category]
        # If it matched more than one category, note that too
        other_categories = [c for c in matches if c != category]

        # Use the most specific matched keyword as the comparable search term
        search_term = matched_keywords[0]

        trademe_result = {"count": 0, "median_price": None, "search_url": ""}
        if not args.dry_run:
            trademe_result = trademe.search_comparables(search_term)

        notes = []
        if trademe_result["count"] and trademe_result["count"] < min_comparables:
            notes.append("Low comparable count on Trade Me -- niche item, price with care")
        elif not trademe_result["count"]:
            notes.append("No Trade Me comparable data (check API key, or search manually)")
        if other_categories:
            notes.append(f"Also matches: {', '.join(other_categories)}")

        report_rows.append({
            "category": category,
            "scanned_at": "",  # filled by report writer's filename timestamp
            "source": listing["source"],
            "title": listing["title"],
            "url": url,
            "matched_keywords": ", ".join(matched_keywords),
            "trademe_comparable_count": trademe_result["count"],
            "trademe_median_price": trademe_result["median_price"] or "",
            "trademe_search_url": trademe_result["search_url"],
            "facebook_search_url": marketplace_search_url(search_term),
            "notes": "; ".join(notes),
        })

    save_seen(new_seen)

    if not report_rows:
        print("[main] no new matching listings this run.")
        return

    path = write_report(report_rows)
    print(f"[main] wrote {len(report_rows)} opportunity row(s) to {path}")

    summary = build_summary(report_rows)
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
