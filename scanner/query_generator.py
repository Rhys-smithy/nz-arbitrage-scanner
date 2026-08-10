"""Phase 3: configurable search-query generation.

Generates web-search queries by combining product/category terms with
bargain-signal concepts and, optionally, a marketplace site: restriction.
This is a *discovery strategy* generator only -- matching one of these
phrases is not itself evidence of a bargain (spec section 5).
"""
from __future__ import annotations

DEFAULT_MARKETPLACE_SITES = ["site:trademe.co.nz"]


def generate_discovery_queries(
    products: list[str],
    concepts: list[str],
    marketplace_sites: list[str] | None = None,
    include_bare_product: bool = True,
    region_suffix: str = "NZ",
) -> list[str]:
    """products: e.g. ["Nintendo Switch", "Canon camera", "Carrera Digital"]
    concepts: e.g. ["bundle", "lot", "moving house", ...]
    marketplace_sites: e.g. ["site:trademe.co.nz"] -- generates one query per
        product restricted to that site, in addition to open-web queries.
    """
    queries: list[str] = []

    for product in products:
        if include_bare_product:
            queries.append(f"{product} {region_suffix}".strip())
        for concept in concepts:
            queries.append(f"{product} {concept} {region_suffix}".strip())
        for site in (marketplace_sites or []):
            queries.append(f"{site} {product}".strip())

    # De-dupe while preserving order (same product/concept pair could recur
    # if caller passes overlapping product lists).
    seen = set()
    unique = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique.append(q)
    return unique


def generate_comparable_queries(product_title: str) -> list[str]:
    """Spec section 8: given a *found* listing, generate research queries
    to find comparable evidence for that specific product."""
    title = product_title.strip()
    if not title:
        return []
    quoted = f'"{title}"'
    return [
        f"{quoted} NZ",
        f"{quoted} sold",
        f"{quoted} price",
        f"{quoted} ebay sold",
        f"site:trademe.co.nz {quoted}",
    ]
