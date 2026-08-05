"""Keyword matching against a listing's title + description, grouped into
categories so results can be sorted/filtered by category in the report."""
from typing import Dict, List, Tuple


def match_categories(text: str, watch_categories: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """Return {category_name: [matched_keywords]} for every category that
    has at least one keyword hit in `text` (case-insensitive)."""
    if not text:
        return {}
    text_lower = text.lower()
    matches = {}
    for category, keywords in watch_categories.items():
        hits = [kw for kw in keywords if kw.lower() in text_lower]
        if hits:
            matches[category] = hits
    return matches


def primary_category(matches: Dict[str, List[str]], category_order: List[str]) -> str:
    """Pick one category to sort/group by: the one with the most keyword
    hits, breaking ties by earliest position in the config's category order
    (so category priority is controlled by the order you list them)."""
    if not matches:
        return "Uncategorised"

    def sort_key(cat: str) -> Tuple[int, int]:
        hit_count = len(matches[cat])
        order_index = category_order.index(cat) if cat in category_order else len(category_order)
        return (-hit_count, order_index)

    return sorted(matches.keys(), key=sort_key)[0]
