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
from urllib.parse import urlsplit

from scanner.evidence import classify_evidence, convert_to_nzd
from scanner.models import ComparableEvidence
from scanner.query_generator import generate_comparable_queries
from scanner.search.util import identify_marketplace

# Captures an explicit currency prefix/symbol (group 1) alongside the
# numeric amount (group 2). A bare "$" is captured but is NOT treated as an
# explicit currency signal downstream -- it's genuinely ambiguous between
# NZD/USD/AUD/etc on its own (see _SYMBOL_CURRENCY below).
_PRICE_RE = re.compile(r"(NZ\$|AU\$|US\$|£|€|\$)\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)")

# Currency implied by an explicit price-string prefix/symbol found in a
# result's own title/description text. This is the most trustworthy signal
# short of a source API field, since it's the source's own words -- but
# only for the unambiguous prefixes; a bare "$" maps to None (unknown), not
# a guess.
_SYMBOL_CURRENCY = {
    "NZ$": "NZD",
    "AU$": "AUD",
    "US$": "USD",
    "£": "GBP",
    "€": "EUR",
    "$": None,
}

_STOPWORDS = {"the", "a", "an", "of", "for", "with", "and", "or", "in", "on", "to", "new", "used"}


def _tokenize(text: str) -> set:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def _title_similarity(a: str, b: str) -> float:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def extract_price_with_currency(text: str) -> tuple[float, str | None] | None:
    """Best-effort price + currency extraction from free text (search
    snippet/title). Returns None if no price pattern matches. The currency
    element is None when the text carries no unambiguous currency signal
    (e.g. a bare "$") -- callers must not treat that None as NZD."""
    if not text:
        return None
    match = _PRICE_RE.search(text)
    if not match:
        return None
    symbol, amount_str = match.group(1), match.group(2)
    try:
        amount = float(amount_str.replace(",", ""))
    except ValueError:
        return None
    return amount, _SYMBOL_CURRENCY.get(symbol)


def extract_price(text: str) -> float | None:
    """Best-effort price extraction from free text (search snippet/title).
    Returns None if nothing matches -- callers must not fall back to a guess.

    Kept as a standalone float-only helper (unchanged signature) because
    scanner/discover.py uses it for discovery-candidate price extraction,
    where only the amount matters. Comparable-evidence building uses
    extract_price_with_currency() below instead, since currency matters
    there."""
    result = extract_price_with_currency(text)
    return result[0] if result else None


# Country-code TLD suffixes that reliably signal a currency on their own --
# a structural signal, not a guess. Deliberately excludes generic TLDs
# (.com, .net, .org, .io, etc.) since those carry no country signal by
# themselves; see _KNOWN_BUSINESS_CURRENCY below for the small, explicit
# set of non-country-TLD businesses whose currency is unambiguous by
# identity rather than by TLD.
_TLD_CURRENCY = {
    ".co.nz": "NZD", ".net.nz": "NZD", ".org.nz": "NZD",
    ".com.au": "AUD", ".net.au": "AUD", ".org.au": "AUD",
    ".co.uk": "GBP", ".org.uk": "GBP",
    ".ca": "CAD",
    ".sg": "SGD",
    ".de": "EUR", ".fr": "EUR", ".it": "EUR", ".es": "EUR",
    ".nl": "EUR", ".eu": "EUR", ".ie": "EUR",
}

# Specific, well-known businesses whose home currency is unambiguous even
# though their domain carries no country-coded TLD. Kept deliberately small
# -- only add a domain here when it's unambiguous by business identity
# (e.g. Kelley Blue Book is inarguably a US institution), never as a way to
# guess at an unfamiliar ".com".
_KNOWN_BUSINESS_CURRENCY = {
    "kbb.com": "USD", "www.kbb.com": "USD",
    "jdpower.com": "USD", "www.jdpower.com": "USD",
    "cycletrader.com": "USD", "www.cycletrader.com": "USD",
    "motorcycle.com": "USD", "www.motorcycle.com": "USD",
}


def _currency_for_domain(url: str) -> str | None:
    """Best-effort currency inference from a result's URL/marketplace.

    Returns None -- never "NZD" -- when nothing here reliably identifies a
    currency. Callers must treat None as genuinely unknown, not as NZD."""
    if not url:
        return None

    marketplace = identify_marketplace(url)
    if marketplace == "eBay":
        return "USD"
    if marketplace == "eBay AU":
        return "AUD"
    if marketplace in ("Trade Me", "Turners", "Thorntons", "Mainland Auctions"):
        return "NZD"

    host = urlsplit(url).netloc.lower()
    if host in _KNOWN_BUSINESS_CURRENCY:
        return _KNOWN_BUSINESS_CURRENCY[host]
    for suffix, currency in _TLD_CURRENCY.items():
        if host.endswith(suffix):
            return currency
    return None


def build_comparables_from_search_results(product_title: str, results: list) -> list[ComparableEvidence]:
    """results: list[SearchResult] already gathered (e.g. from WebSearchSource.search()
    across the queries from generate_comparable_queries())."""
    evidence: list[ComparableEvidence] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for r in results:
        text = f"{r.title} {r.description}"
        if r.price is not None:
            raw_price, text_currency = r.price, None
        else:
            extracted = extract_price_with_currency(text)
            if extracted is None:
                continue
            raw_price, text_currency = extracted
        if raw_price is None:
            continue

        # Currency precedence: an explicit, non-blank currency the source
        # itself reports (r.currency) > an explicit currency prefix/symbol
        # found in the priced text itself (e.g. "US$4,990") > reliable
        # domain/marketplace inference. A bare "$" is NOT an explicit
        # signal (ambiguous between NZD/USD/AUD/etc), so it falls through
        # to domain inference just like unmarked text would. This never
        # defaults to NZD -- search providers must not (and no longer do)
        # hardcode a currency they don't actually know (see
        # scanner/search/providers/*.py).
        currency = r.currency or text_currency or _currency_for_domain(r.url)

        evidence_type = classify_evidence(r.url, r.title, r.description, is_explicitly_sold=r.is_sold)
        similarity = _title_similarity(product_title, r.title)

        if currency is None:
            # Genuinely unknown currency: never silently assume NZD, and
            # never apply an unverified conversion. The evidence stays
            # visible (same "never hidden" principle as the similarity
            # floor in scanner/comparables.py) so a human can see a price
            # was found, but price is left unset so it can never enter
            # pricing/confidence math -- comparables.py's `qualified`
            # filter requires a truthy price, and estimate_liquidity()
            # never looks at price at all, so liquidity is unaffected
            # either way.
            evidence.append(
                ComparableEvidence(
                    product=product_title,
                    model="",
                    condition="unknown",
                    price=None,
                    currency="unknown",
                    source=identify_marketplace(r.url),
                    url=r.url,
                    date_observed=r.timestamp or now_iso,
                    similarity_score=similarity,
                    is_sold=(evidence_type == "SOLD"),
                    evidence_type=evidence_type,
                    original_price=raw_price,
                    original_currency=None,
                )
            )
            continue

        price_nzd, converted = convert_to_nzd(raw_price, currency)

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
