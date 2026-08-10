"""URL canonicalisation, marketplace identification, and dedup helpers (Phase 3)."""
from __future__ import annotations

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
    "mainlandauctions.nz": "Mainland Auctions",
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
