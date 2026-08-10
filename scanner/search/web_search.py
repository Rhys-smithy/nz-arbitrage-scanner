"""Phase 3: real web-search source, backed by a configurable provider.

Set WEB_SEARCH_PROVIDER=tavily (+ TAVILY_API_KEY) -- free tier, no card,
recommended default -- or =brave (+ BRAVE_API_KEY) / =serpapi
(+ SERPAPI_API_KEY) if you have paid access to those. With no provider
configured, this source honestly reports itself unavailable and returns
no results -- it never fabricates data (spec section 3/12/20).

No provider here scrapes a search engine's HTML or bypasses its
protections; each one calls a documented, ToS-permitted REST API.
"""
from __future__ import annotations

import os

from scanner.search.base import SearchResult, SearchSource
from scanner.search.providers.tavily import TavilySearchProvider
from scanner.search.providers.brave import BraveSearchProvider
from scanner.search.providers.serpapi import SerpApiSearchProvider

# tavily: free tier, no credit card, recommended default (see README).
# brave / serpapi: no meaningful free tier as of Feb 2026 -- paid, kept as
# swappable options only, NOT selected unless explicitly configured.
_PROVIDERS = {
    "tavily": TavilySearchProvider,
    "brave": BraveSearchProvider,
    "serpapi": SerpApiSearchProvider,
}


class WebSearchSource(SearchSource):
    name = "web_search"

    def __init__(self):
        provider_name = os.environ.get("WEB_SEARCH_PROVIDER", "").strip().lower()
        provider_cls = _PROVIDERS.get(provider_name)
        self._provider = provider_cls() if provider_cls else None
        self.available = bool(self._provider and self._provider.is_configured())
        if provider_name and provider_name not in _PROVIDERS:
            print(f"[search/web_search] Unknown WEB_SEARCH_PROVIDER={provider_name!r}; "
                  f"supported: {list(_PROVIDERS)}. No results will be returned.")
        elif not provider_name:
            print("[search/web_search] WEB_SEARCH_PROVIDER not set -- web search disabled, "
                  "no results fabricated.")

    def search(self, query: str, **kwargs) -> list[SearchResult]:
        if not self.available:
            return []
        return self._provider.search(query, **kwargs)
