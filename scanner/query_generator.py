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


def allocate_discovery_queries(
    products: list[str],
    concepts: list[str],
    max_queries: int = 15,
    include_bare_product: bool = True,
    region_suffix: str = "NZ",
) -> list[str]:
    """Phase 4A fix: distribute the query budget evenly across every
    configured product instead of exhausting it on the first one.

    Root cause (Run #23): generate_discovery_queries() is product-major --
    it emits ALL of one product's queries (bare + every concept + site)
    before moving to the next product. With 12 configured products and 13
    concepts, product #1 alone generates 1 + 13 = 14 queries, so slicing
    to max_queries_per_run=15 left products 2-12 with zero queries.

    This instead builds each product's query list (bare product first,
    then concepts in order) and round-robins one query per product per
    round, so every product gets at least one query whenever
    max_queries >= len(products).

    Domain restriction (NZ-local marketplaces only, no eBay) is applied
    separately via the search provider's include_domains parameter at
    search time (see scanner/discover.py) -- it is deliberately NOT baked
    into the query text here, since a literal "site:" prefix is not a
    real filter for every provider (that was part of the Run #23 bug).
    """
    if not products or max_queries <= 0:
        return []

    per_product: list[list[str]] = []
    for product in products:
        product_queries: list[str] = []
        if include_bare_product:
            product_queries.append(f"{product} {region_suffix}".strip())
        for concept in concepts:
            product_queries.append(f"{product} {concept} {region_suffix}".strip())
        per_product.append(product_queries)

    allocated: list[str] = []
    seen: set[str] = set()
    round_idx = 0
    max_len = max((len(pq) for pq in per_product), default=0)
    while len(allocated) < max_queries and round_idx < max_len:
        for product_queries in per_product:
            if len(allocated) >= max_queries:
                break
            if round_idx < len(product_queries):
                query = product_queries[round_idx]
                if query not in seen:
                    seen.add(query)
                    allocated.append(query)
        round_idx += 1

    return allocated


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
