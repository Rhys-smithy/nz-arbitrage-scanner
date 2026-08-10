"""Tavily Search API provider (https://tavily.com).

Recommended default: 1,000 free API credits/month, no credit card required
(as of research done August 2026 -- verify current terms before relying on
this long-term, provider terms change). Basic search = 1 credit/request.
Supports include_domains for site-restricted queries (used for
`site:trademe.co.nz`-style discovery instead of Google's `site:` operator).
"""
from __future__ import annotations

import os

import requests

from scanner.search.base import SearchResult
from scanner.search.providers.base import SearchProvider

API_URL = "https://api.tavily.com/search"

# Tavily's time_range param: day/week/month/year
_FRESHNESS_MAP = {"day": "day", "week": "week", "month": "month", "year": "year"}


class TavilySearchProvider(SearchProvider):
    name = "tavily"

    def __init__(self):
        self._api_key = os.environ.get("TAVILY_API_KEY", "")

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def search(
        self,
        query: str,
        location: str = "New Zealand",
        freshness: str | None = None,
        max_results: int = 10,
        include_domains: list[str] | None = None,
    ) -> list[SearchResult]:
        if not self.is_configured():
            print("[search/tavily] TAVILY_API_KEY not set -- skipping (no results fabricated).")
            return []

        payload = {
            "api_key": self._api_key,
            "query": query,
            "search_depth": "basic",  # 1 credit/request; "advanced" costs 2
            "max_results": min(max_results, 20),
        }
        if freshness in _FRESHNESS_MAP:
            payload["time_range"] = _FRESHNESS_MAP[freshness]
        if include_domains:
            payload["include_domains"] = include_domains

        try:
            resp = requests.post(API_URL, json=payload, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            print(f"[search/tavily] request failed for query {query!r}: {e}")
            return []
        except ValueError as e:
            print(f"[search/tavily] invalid JSON response for query {query!r}: {e}")
            return []

        if "error" in data:
            print(f"[search/tavily] provider error for query {query!r}: {data['error']}")
            return []

        results = []
        for item in data.get("results", []) or []:
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    price=None,
                    currency="NZD",
                    source="web_search:tavily",
                    description=item.get("content", ""),
                    condition="unknown",
                    is_sold=False,
                )
            )
        return results
