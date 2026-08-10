"""Filters applied before scoring: price cap and excluded-condition keywords
(damaged/faulty/broken/etc). Keeping this as simple keyword matching rather
than relying solely on the AI to self-exclude, since a hard filter is more
reliable than hoping every prompt call correctly downweights a bad item."""
from typing import Dict, List, Optional


def exceeds_price_cap(item: Dict, max_price_nzd: Optional[float]) -> bool:
    if not max_price_nzd:
        return False
    for key in ("price", "buy_now_price"):
        value = item.get(key)
        if value is not None and value > max_price_nzd:
            return True
    return False


def matches_exclude_keywords(text: str, keywords: List[str]) -> bool:
    if not text or not keywords:
        return False
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def passes_initial_filters(item: Dict, config: Dict) -> bool:
    """Filter applied right after scraping, before any detail fetch or
    grouping -- title + price only, since that's all we have yet."""
    # Turners lists some lots as "Pricing coming soon" with no bid at all --
    # there's nothing to value, so drop them before spending an AI call. Lots
    # that simply haven't opened yet ("opens_soon") are kept.
    if item.get("pricing_status") == "no_pricing":
        return False
    if exceeds_price_cap(item, config.get("max_price_nzd")):
        return False
    if matches_exclude_keywords(item.get("title", ""), config.get("exclude_keywords", [])):
        return False
    return True


def passes_detail_filters(item: Dict, config: Dict) -> bool:
    """Second-pass filter applied after fetching condition/comments, since
    "damaged" often only shows up in the item detail text, not the title."""
    combined = f"{item.get('condition', '')} {item.get('comments', '')}"
    if matches_exclude_keywords(combined, config.get("exclude_keywords", [])):
        return False
    return True
