"""Trade Me / Facebook Marketplace reference-link source.

Neither site's terms permit scraping listings/prices here (Trade Me's API
excludes this kind of personal-use resale-comparison use case without a
commercial agreement; Facebook Marketplace has no public API and scraping
it means defeating bot detection, which the spec explicitly forbids).

This source therefore only builds manual search URLs (reusing the
existing scanner/trademe_links.py and scanner/facebook.py helpers) for a
human to check, and never returns fabricated SearchResult price data.
"""
from __future__ import annotations

from scanner.trademe_links import trademe_search_url
from scanner.facebook import marketplace_search_url
from scanner.search.base import SearchResult, SearchSource


class MarketplaceSearchSource(SearchSource):
    name = "marketplace"
    available = False  # link-builder only, no permitted automated data access

    def search(self, query: str, **kwargs) -> list[SearchResult]:
        return []

    def reference_urls(self, query: str, location: str = "") -> dict:
        return {
            "trademe": trademe_search_url(query),
            "facebook": marketplace_search_url(query, location),
        }
