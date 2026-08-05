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
    try:
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"[notifier] Telegram send failed ({resp.status_code}): {resp.text[:300]}")
            return False
        return True
    except requests.RequestException as e:
        print(f"[notifier] Telegram send failed: {e}")
        return False


def build_summary(rows, max_items_per_category: int = 5) -> str:
    """Build a compact HTML-formatted summary grouped by category.

    Telegram caps messages at 4096 characters. Rather than truncating the
    final string blindly (which can slice through an HTML tag and make
    Telegram reject the whole message), this builds a list of whole lines
    and stops adding lines once close to the budget -- so whatever gets
    sent is always valid, balanced HTML, just possibly a shorter list."""
    if not rows:
        return ""

    CHAR_BUDGET = 3800  # leaves headroom below Telegram's 4096 hard limit

    by_category = {}
    for row in rows:
        by_category.setdefault(row["category"], []).append(row)

    header = f"<b>NZ Auction Scanner — {len(rows)} new match(es)</b>\n"
    lines = [header]
    total_len = len(header)
    omitted_categories = 0
    omitted_items = 0

    for category in sorted(by_category.keys()):
        items = sorted(by_category[category], key=lambda r: (r.get("score") is None, -(r.get("score") or 0)))
        category_lines = [f"\n<b>{category}</b> ({len(items)})"]

        shown = 0
        for row in items[:max_items_per_category]:
            score = row.get("score")
            score_note = f" [{score}/10]" if score is not None else ""
            price = row.get("price_nzd")
            price_note = f" — ${price}" if price != "" and price is not None else ""
            item_lines = [f'• <a href="{row["url"]}">{row["title"]}</a>{price_note}{score_note}']
            explanation = row.get("explanation", "")
            if explanation:
                item_lines.append(f"  <i>{explanation[:150]}</i>")

            item_block_len = sum(len(l) + 1 for l in item_lines)
            if total_len + sum(len(l) + 1 for l in category_lines) + item_block_len > CHAR_BUDGET:
                omitted_items += len(items) - shown
                break
            category_lines.extend(item_lines)
            shown += 1

        if len(items) > shown:
            note = f"  ...and {len(items) - shown} more in this category"
            if total_len + sum(len(l) + 1 for l in category_lines) + len(note) + 1 <= CHAR_BUDGET:
                category_lines.append(note)

        category_block_len = sum(len(l) + 1 for l in category_lines)
        if total_len + category_block_len > CHAR_BUDGET:
            omitted_categories += 1
            continue

        lines.extend(category_lines)
        total_len += category_block_len

    if omitted_categories:
        lines.append(f"\n\n<i>+{omitted_categories} more categor{'y' if omitted_categories == 1 else 'ies'} in the full CSV report</i>")

    return "\n".join(lines)
