"""Phase 3 section 8/9/10: real comparable-evidence research.

Turns a product title into search-provider queries, then classifies and
converts whatever the configured web-search provider actually returns
into ComparableEvidence. Never invents a price -- if a search result's
snippet has no extractable price, it's kept (as OTHER/context) but not
counted as a priced comparable.

This feeds scanner/comparables.py's existing build_valuation_from_evidence()
(Phase 2) -- it does NOT reimplement valuation math.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from scanner.evidence import classify_evidence, convert_to_nzd
from scanner.models import ComparableEvidence
from scanner.query_generator import generate_comparable_queries
from scanner.search.util import identify_marketplace

_PRICE_RE = re.compile(r"(?:NZ\$|AU\$|US\$|£|€|\$)\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)")

_STOPWORDS = {"the", "a", "an", "of", "for", "with", "and", "or", "in", "on", "to", "new", "used"}


def _tokenize(text: str) -> set:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def _title_similarity(a: str, b: str) -> float:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def extract_price(text: str) -> float | None:
    """Best-effort price extraction from free text (search snippet/title).
    Returns None if nothing matches -- callers must not fall back to a guess."""
    if not text:
        return None
    match = _PRICE_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _currency_for_domain(url: str) -> str:
    marketplace = identify_marketplace(url)
    if marketplace in ("eBay",):
        return "USD"
    if "ebay.com.au" in (url or ""):
        return "AUD"
    return "NZD"


def build_comparables_from_search_results(product_title: str, results: list) -> list[ComparableEvidence]:
    """results: list[SearchResult] already gathered (e.g. from WebSearchSource.search()
    across the queries from generate_comparable_queries())."""
    evidence: list[ComparableEvidence] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for r in results:
        text = f"{r.title} {r.description}"
        raw_price = r.price if r.price is not None else extract_price(text)
        if raw_price is None:
            continue  # no priced evidence to extract from this result -- skip, don't guess

        currency = r.currency or _currency_for_domain(r.url)
        price_nzd, converted = convert_to_nzd(raw_price, currency)

        evidence_type = classify_evidence(r.url, r.title, r.description, is_explicitly_sold=r.is_sold)
        similarity = _title_similarity(product_title, r.title)

        evidence.append(
            ComparableEvidence(
                product=product_title,
                model="",
                condition="unknown",
                price=price_nzd,
                currency="NZD",
                source=identify_marketplace(r.url),
                url=r.url,
                date_observed=r.timestamp or now_iso,
                similarity_score=similarity,
                is_sold=(evidence_type == "SOLD"),
                evidence_type=evidence_type,
                original_price=raw_price if converted else None,
                original_currency=currency if converted else None,
            )
        )
    return evidence


def research_comparables(
    product_title: str,
    search_source,
    max_results_per_query: int = 10,
    exclude_url: str | None = None,
) -> list[ComparableEvidence]:
    """End-to-end: generate queries -> run them through `search_source`
    (anything with a .search(query, max_results=...) method, e.g.
    scanner.search.web_search.WebSearchSource) -> classify + convert.

    `exclude_url` should be the URL of the listing being valued itself --
    without this, a listing can end up cited as its own comparable
    evidence when it reappears in search results for its own product name.

    If the search source is unavailable (no credentials), this returns an
    empty list -- callers should treat that as "insufficient evidence",
    not silently proceed as if evidence existed.
    """
    if not getattr(search_source, "available", False):
        return []

    from scanner.search.util import canonicalize_url
    exclude_key = canonicalize_url(exclude_url) if exclude_url else None

    all_results = []
    for query in generate_comparable_queries(product_title):
        for r in search_source.search(query, max_results=max_results_per_query):
            if exclude_key and canonicalize_url(r.url) == exclude_key:
                continue
            all_results.append(r)

    return build_comparables_from_search_results(product_title, all_results)
