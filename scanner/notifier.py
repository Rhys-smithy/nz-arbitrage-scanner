"""
Sends a summary message to a Telegram chat so results show up as a phone
notification. Telegram bots are free and take about 2 minutes to set up --
see README.md for the BotFather steps.
"""
import requests


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    if not bot_token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    # Telegram messages are capped at 4096 characters -- trim if needed.
    if len(text) > 4000:
        text = text[:3980] + "\n...(truncated, see full CSV report)"
    try:
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15,
        )
        return resp.status_code == 200
    except requests.RequestException as e:
        print(f"[notifier] Telegram send failed: {e}")
        return False


def build_summary(rows, max_items_per_category: int = 5) -> str:
    """Build a compact HTML-formatted summary grouped by category, capped
    per category so the message doesn't blow past Telegram's length limit."""
    if not rows:
        return ""

    by_category = {}
    for row in rows:
        by_category.setdefault(row["category"], []).append(row)

    lines = [f"<b>NZ Auction Scanner — {len(rows)} new match(es)</b>\n"]
    for category in sorted(by_category.keys()):
        items = by_category[category]
        lines.append(f"\n<b>{category}</b> ({len(items)})")
        for row in items[:max_items_per_category]:
            price = row.get("trademe_median_price")
            price_note = f" — TM median ${price}" if price else ""
            lines.append(f'• <a href="{row["url"]}">{row["title"]}</a>{price_note}')
        if len(items) > max_items_per_category:
            lines.append(f"  ...and {len(items) - max_items_per_category} more in this category")

    return "\n".join(lines)
