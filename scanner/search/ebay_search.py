"""eBay comparable-evidence source.

IMPORTANT: this repo has no eBay API credentials and this source does not
scrape eBay directly (no bot-detection evasion, per spec). It only builds
a legitimate "sold + completed listings" search URL (existing
scanner/ebay_links.py) for a human -- or a future properly-authorised
eBay Browse/Marketplace Insights API integration -- to consult.

Because no structured data is actually fetched, this source returns an
empty result list and is marked unavailable for automated evidence. It
still exposes the search URL via `.reference_url()` so callers can surface
it to the user as "check here" rather than inventing a price.
"""
from __future__ import annotations

from scanner.ebay_links import ebay_sold_search_url
from scanner.search.base import SearchResult, SearchSource


class EbaySearchSource(SearchSource):
    name = "ebay"
    available = False  # no API credentials configured -> cannot supply automated evidence

    def search(self, query: str, **kwargs) -> list[SearchResult]:
        # Deliberately returns no fabricated results. Real eBay sold-price
        # evidence requires either the eBay Marketplace Insights API
        # (partner-gated) or a human clicking through reference_url().
        return []

    def reference_url(self, query: str) -> str:
        return ebay_sold_search_url(query)
