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


def _round_robin_fill(
    per_product_lists: list[list[str]],
    budget: int,
    seen: set[str],
    sink: list[str],
) -> None:
    """Col-major round robin: appends up to `budget` (total, including
    anything already in `sink`) new queries into `sink`, taking one query
    per product per round, skipping anything already in `seen`. Mutates
    `seen`/`sink` in place."""
    round_idx = 0
    max_len = max((len(pq) for pq in per_product_lists), default=0)
    while len(sink) < budget and round_idx < max_len:
        for product_queries in per_product_lists:
            if len(sink) >= budget:
                break
            if round_idx < len(product_queries):
                query = product_queries[round_idx]
                if query not in seen:
                    seen.add(query)
                    sink.append(query)
        round_idx += 1


def allocate_discovery_queries(
    products: list[str],
    concepts: list[str],
    max_queries: int = 15,
    include_bare_product: bool = True,
    region_suffix: str = "NZ",
    bare_product_min_ratio: float = 0.15,
    seed: int = 0,
) -> list[str]:
    """Phase 4A fix (Run #23) + rebalance fix (known issue from PR #5
    review / PROJECT_STATE.md): distribute the query budget across every
    configured product, weighted toward bargain-signal concept queries
    rather than bare-product queries, and rotate which products/concepts
    get priority across runs instead of always favouring the same ones.

    Root cause of Run #23: generate_discovery_queries() is product-major --
    it emits ALL of one product's queries before moving to the next, so a
    tight budget could leave later products with zero queries. Fixed by
    round-robinning one query per product per round (unchanged here).

    Root cause of the rebalance issue: the original round-robin put each
    product's bare-product query (e.g. "Nintendo Switch NZ" -- no bargain
    signal at all) first in its per-product list, so round 0 -- the round
    that always runs first and gets guaranteed budget -- was ALL bare-
    product queries. With 12 products and a 15-query budget that's 12 of
    15 slots (80%) on the weakest query shape, leaving only 3 slots for
    concept queries, all going to the first 3 products in config order
    (config order never changes, so it's the *same* 3 products and the
    *same* 1 concept every single run, forever -- 12 of 13 configured
    bargain-signal concepts and 9 of 12 products never got a concept query
    at all).

    Fix: concept queries are now prioritised first (they carry the actual
    bargain signal this pipeline exists to find), with only a small
    reserved floor -- `bare_product_min_ratio` of the budget (default
    ~15%, configurable via config.json's query_generation.
    bare_product_min_ratio) -- guaranteed for bare-product queries, since
    those do still catch naive underpricing that doesn't use any of our
    configured bargain words. `seed` rotates which products/concepts get
    priority each run (callers should pass something that changes daily,
    e.g. a date ordinal -- see scanner/discover.py) so coverage cycles
    across the full product/concept lists over time instead of camping on
    whatever happens to be first in config.json.

    Domain restriction (NZ-local marketplaces only, no eBay) is applied
    separately via the search provider's include_domains parameter at
    search time (see scanner/discover.py) -- it is deliberately NOT baked
    into the query text here, since a literal "site:" prefix is not a
    real filter for every provider (that was part of the Run #23 bug).
    """
    if not products or max_queries <= 0:
        return []

    def _rotate(items: list[str], offset: int) -> list[str]:
        if not items:
            return []
        offset %= len(items)
        return items[offset:] + items[:offset]

    products_rotated = _rotate(products, seed)
    concepts_rotated = _rotate(concepts, seed)

    if include_bare_product and bare_product_min_ratio > 0:
        bare_floor = max(1, round(max_queries * bare_product_min_ratio))
        bare_floor = min(bare_floor, max_queries, len(products_rotated))
    else:
        bare_floor = 0
    concept_budget = max_queries - bare_floor

    per_product_concepts = (
        [[f"{p} {c} {region_suffix}".strip() for c in concepts_rotated] for p in products_rotated]
        if concepts_rotated
        else []
    )

    allocated: list[str] = []
    seen: set[str] = set()

    _round_robin_fill(per_product_concepts, concept_budget, seen, allocated)

    if include_bare_product:
        bare_target = len(allocated) + bare_floor
        for p in products_rotated:
            if len(allocated) >= bare_target:
                break
            query = f"{p} {region_suffix}".strip()
            if query not in seen:
                seen.add(query)
                allocated.append(query)

    # Backfill any leftover budget -- happens only when there aren't enough
    # distinct product/concept combinations to fill the split above (e.g.
    # very few products/concepts configured). Prefer more concept coverage
    # first, then additional bare-product queries, so budget never goes
    # unused while genuinely novel queries still exist.
    if len(allocated) < max_queries:
        _round_robin_fill(per_product_concepts, max_queries, seen, allocated)
    if include_bare_product and len(allocated) < max_queries:
        for p in products_rotated:
            if len(allocated) >= max_queries:
                break
            query = f"{p} {region_suffix}".strip()
            if query not in seen:
                seen.add(query)
                allocated.append(query)

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
