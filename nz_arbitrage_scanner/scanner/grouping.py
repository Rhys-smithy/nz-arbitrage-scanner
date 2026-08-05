"""
Groups items with similar titles (e.g. multiple "18V Drill" listings) so
they can be compared against each other on price + condition. Rule-based
token-overlap matching rather than an ML/embedding approach -- keeps this
free and fast, at the cost of being a blunter match than semantic
similarity would give you. Good enough for "these are probably the same
kind of item," not perfect brand/model matching.
"""
import re
from typing import Dict, List

# Words too generic to count toward similarity (auction-listing filler)
_STOPWORDS = {
    "the", "a", "an", "of", "for", "with", "and", "or", "in", "on", "to",
    "new", "used", "bulk", "assorted", "various", "lot", "set", "pack",
    "x", "no", "not", "tested", "untested",
}


def _tokenize(title: str) -> set:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def group_similar_items(items: List[Dict], min_group_size: int = 2, similarity_threshold: float = 0.5) -> List[List[Dict]]:
    """Groups items whose titles share enough tokens (Jaccard similarity)
    to likely be the same kind of item. Returns only groups with at least
    `min_group_size` items -- singletons are dropped since there's nothing
    to compare them against."""
    tokenized = [(item, _tokenize(item["title"])) for item in items]
    used = set()
    groups = []

    for i, (item_a, tokens_a) in enumerate(tokenized):
        if i in used or not tokens_a:
            continue
        group = [item_a]
        group_indices = {i}
        for j, (item_b, tokens_b) in enumerate(tokenized):
            if j <= i or j in used or not tokens_b:
                continue
            union = tokens_a | tokens_b
            intersection = tokens_a & tokens_b
            similarity = len(intersection) / len(union) if union else 0
            if similarity >= similarity_threshold:
                group.append(item_b)
                group_indices.add(j)

        if len(group) >= min_group_size:
            used |= group_indices
            groups.append(group)

    return groups
