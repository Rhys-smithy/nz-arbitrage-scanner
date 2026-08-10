"""URL canonicalisation, marketplace identification, and dedup helpers (Phase 3)."""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

# Query params that don't change what page is being viewed -- strip them so
# the same listing found via different search queries/referrers dedupes to
# one canonical URL.
_TRACKING_PARAM_PREFIXES = ("utm_", "gclid", "fbclid", "ref", "src", "cid", "affid")

_MARKETPLACE_DOMAINS = {
    "trademe.co.nz": "Trade Me",
    "www.trademe.co.nz": "Trade Me",
    "facebook.com": "Facebook Marketplace",
    "www.facebook.com": "Facebook Marketplace",
    "ebay.com.au": "eBay AU",
    "www.ebay.com.au": "eBay AU",
    "ebay.com": "eBay",
    "www.ebay.com": "eBay",
    "turners.co.nz": "Turners",
    "www.turners.co.nz": "Turners",
    "thorntons.net.nz": "Thorntons",
    "www.thorntons.net.nz": "Thorntons",
    "mainlandauctions.nz": "Mainland Auctions",
    "www.mainlandauctions.nz": "Mainland Auctions",
}


def canonicalize_url(url: str) -> str:
    """Normalise a URL for dedup purposes: lowercase host, strip tracking
    params, strip fragment, strip trailing slash."""
    if not url:
        return url
    parts = urlsplit(url.strip())
    scheme = "https"  # treat http/https as equivalent for dedup
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    query_pairs = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not any(k.lower().startswith(p) for p in _TRACKING_PARAM_PREFIXES)
    ]
    query_pairs.sort()
    query = urlencode(query_pairs)
    return urlunsplit((scheme, netloc, path, query, ""))


def identify_marketplace(url: str) -> str:
    if not url:
        return "unknown"
    host = urlsplit(url).netloc.lower()
    return _MARKETPLACE_DOMAINS.get(host, host or "unknown")


# Per-marketplace URL *path* shapes that identify an individual listing/lot
# page, as opposed to a category, browse, or search page on the same
# domain. Discovery's web search results land on both shapes indiscriminately
# -- only individual listing pages carry a real price to extract and value.
_LISTING_PATH_PATTERNS = {
    "Trade Me": re.compile(r"/listing/\d+"),
    "Facebook Marketplace": re.compile(r"/marketplace/item/\d+"),
    "eBay": re.compile(r"/itm/(?:[\w\-]+/)?\d+"),
    "eBay AU": re.compile(r"/itm/(?:[\w\-]+/)?\d+"),
    # Turners General Goods catalog items end in a numeric id
    # (/General-Goods/Search/<cat>/<subcat>/<id>/); vehicle detail pages are
    # any path ending in a 5+ digit id. Category/search pages match neither.
    "Turners": re.compile(
        r"(?:/General-Goods/Search/[a-z0-9\-]+/[a-z0-9\-]+/\d+|/\d{5,})/?$",
        re.IGNORECASE,
    ),
    "Thorntons": re.compile(r"/auctions/detail/"),
    "Mainland Auctions": re.compile(r"^/auctions/[a-z0-9\-]+/?$", re.IGNORECASE),
}


def is_individual_listing_url(url: str) -> bool:
    """True only for URLs pointing at a single listing/lot/item page on a
    recognised marketplace.

    Two things get filtered out, not just one:
    1. Non-marketplace domains -- YouTube videos, Etsy category pages,
       retailer collection pages, news, etc. (identify_marketplace() alone
       does NOT exclude these; it happily returns the bare hostname for any
       domain it doesn't recognise, so a naive "!= unknown" check lets
       everything but empty/malformed URLs through).
    2. Category/browse/search pages *on* a recognised marketplace domain --
       e.g. a Trade Me category page has no real single-item price to
       extract, so treating it as a candidate produces nonsense prices
       scraped from incidental page text.
    """
    if not url:
        return False
    marketplace = identify_marketplace(url)
    pattern = _LISTING_PATH_PATTERNS.get(marketplace)
    if pattern is None:
        return False
    return bool(pattern.search(urlsplit(url).path))


def dedupe_results(results: list) -> list:
    """Dedupe a list of SearchResult by canonical URL, keeping the first
    occurrence (search order determines priority -- callers should search
    highest-trust sources first if order matters)."""
    seen = set()
    deduped = []
    for r in results:
        key = canonicalize_url(r.url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped
