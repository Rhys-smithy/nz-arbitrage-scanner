"""
Sends the scan results to a Telegram chat as one or more messages (split
across multiple messages rather than truncated, so nothing gets cut off --
Telegram caps a single message at 4096 characters, and with full
explanations for every item this often needs more than one). Telegram
bots are free and take about 2 minutes to set up -- see README.md for the
BotFather steps.
"""
import time
import os
import requests

CHAR_BUDGET = 3800  # leaves headroom below Telegram's 4096 hard limit


def send_telegram_document(bot_token: str, chat_id: str, filepath: str, caption: str = "") -> bool:
    """Sends a file (e.g. the xlsx report) directly into the Telegram chat
    as a document attachment, so it's one tap away instead of needing to
    dig through GitHub Actions artifacts."""
    if not bot_token or not chat_id or not os.path.exists(filepath):
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    try:
        with open(filepath, "rb") as f:
            resp = requests.post(
                url,
                data={"chat_id": chat_id, "caption": caption[:1024]},
                files={"document": (os.path.basename(filepath), f)},
                timeout=60,
            )
        if resp.status_code != 200:
            print(f"[notifier] Telegram document send failed ({resp.status_code}): {resp.text[:300]}")
            return False
        return True
    except requests.RequestException as e:
        print(f"[notifier] Telegram document send failed: {e}")
        return False


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    if not bot_token or not chat_id or not text:
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


def send_telegram_messages(bot_token: str, chat_id: str, messages: list) -> bool:
    """Sends each message in sequence with a small delay between them
    (Telegram rate-limits rapid-fire messages). Returns True only if every
    message sent successfully."""
    all_ok = True
    for i, msg in enumerate(messages):
        ok = send_telegram_message(bot_token, chat_id, msg)
        all_ok = all_ok and ok
        if i < len(messages) - 1:
            time.sleep(1.5)
    return all_ok


def build_summary(rows) -> list:
    """Build one or more HTML-formatted Telegram messages covering every
    row in full -- explanations are never truncated. Splits into multiple
    messages at whole-category or whole-item boundaries only, so nothing
    is ever cut mid-sentence or mid-HTML-tag. Returns a list of message
    strings (usually 1, more if there's a lot of content)."""
    if not rows:
        return []

    by_category = {}
    for row in rows:
        by_category.setdefault(row["category"], []).append(row)

    header = f"<b>NZ Auction Scanner — {len(rows)} new match(es)</b>"
    messages = []
    current_lines = [header]
    current_len = len(header)

    def flush():
        nonlocal current_lines, current_len
        if current_lines:
            messages.append("\n".join(current_lines))
        current_lines = []
        current_len = 0

    for category in sorted(by_category.keys()):
        items = sorted(by_category[category], key=lambda r: (r.get("score") is None, -(r.get("score") or 0)))
        category_lines = [f"\n<b>{category}</b> ({len(items)})"]

        for row in items:
            score = row.get("score")
            score_note = f" [{score}/10]" if score is not None else ""
            price = row.get("price_nzd")
            price_note = f" — ${price}" if price != "" and price is not None else ""
            resale = row.get("resale_likelihood")
            resale_note = {"high": " 🔁high resale", "medium": " 🔁med resale", "low": " 🔁low resale"}.get(resale, "")
            profit = row.get("potential_profit_nzd")
            resell_price = row.get("suggested_resale_price_nzd")
            profit_note = ""
            if profit != "" and profit is not None and resell_price != "" and resell_price is not None:
                profit_note = f" → resell ~${resell_price} ({'+' if profit >= 0 else ''}${profit})"
            item_lines = [f'• <a href="{row["url"]}">{row["title"]}</a>{price_note}{score_note}{resale_note}{profit_note}']
            explanation = row.get("explanation", "")
            if explanation:
                item_lines.append(f"  <i>{explanation}</i>")

            item_block = "\n".join(item_lines)
            item_block_len = len(item_block) + 1

            # If a single item's own content is bigger than the whole
            # budget (extremely long explanation), it still gets its own
            # dedicated message rather than being cut.
            if item_block_len > CHAR_BUDGET:
                if current_lines:
                    flush()
                messages.append(item_block)
                continue

            if current_len + sum(len(l) + 1 for l in category_lines) + item_block_len > CHAR_BUDGET:
                # Current message is full -- start a fresh one, repeating
                # the category header so the new message has context.
                flush()
                category_lines = [f"<b>{category}</b> (continued)"]

            category_lines.append(item_block)

        block_len = sum(len(l) + 1 for l in category_lines)
        if current_len + block_len > CHAR_BUDGET:
            flush()
        current_lines.extend(category_lines)
        current_len += block_len

    flush()

    if len(messages) > 1:
        for i in range(len(messages)):
            messages[i] += f"\n\n<i>(message {i + 1}/{len(messages)})</i>"

    return messages


def build_flip_alert(opportunity) -> str:
    """Phase 2I: rich per-opportunity alert format (spec section 21).

    Takes a scanner.models.Opportunity. Purely a string formatter --
    does not send anything itself, so it's reused by both the
    flip-hunter demo pipeline and can be unit tested without network I/O.
    """
    o = opportunity
    val = o.valuation
    lines = ["\U0001F525 <b>FLIP ALERT</b>", "", f"<b>{o.title}</b>", ""]
    lines.append(f"Current: ${o.current_price:.0f}" if o.current_price is not None else "Current: unknown")
    if o.max_buy_price is not None:
        lines.append(f"Maximum buy: ${o.max_buy_price:.0f}")
    lines.append("")
    if val.quick_sale_low is not None:
        lines.append(f"Quick-sale resale: ${val.quick_sale_low:.0f}-{val.quick_sale_high:.0f}")
    if o.expected_net_profit_low is not None:
        lines.append(f"Expected net profit: ${o.expected_net_profit_low:.0f}")
    if o.roi_low_pct is not None:
        lines.append(f"ROI: {o.roi_low_pct:.0f}%")
    lines.append("")
    if o.flip_score is not None:
        lines.append(f"Flip score: {o.flip_score}/100")
    lines.append(f"Confidence: {val.confidence_pct:.0f}%")
    lines.append(f"Liquidity: {o.liquidity}")
    lines.append("")
    if o.bidding_room is not None:
        lines.append(f"${o.bidding_room:.0f} bidding room remaining.")
    lines.append("")
    lines.append(f"Decision: {o.decision}")
    lines.append(f'<a href="{o.url}">Listing</a>')
    return "\n".join(lines)
