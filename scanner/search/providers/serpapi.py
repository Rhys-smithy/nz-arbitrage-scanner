"""SerpApi provider (https://serpapi.com) -- Google search results via a
licensed third-party API, not direct scraping of google.com. Requires
SERPAPI_API_KEY. Useful as a fallback/alternative to Brave, or for
`site:trademe.co.nz` style queries if Brave's coverage is thin.
"""
from __future__ import annotations

import os

import requests

from scanner.search.base import SearchResult
from scanner.search.providers.base import SearchProvider

API_URL = "https://serpapi.com/search"

# SerpApi's Google `tbs` recency param (qdr:d/w/m/y)
_FRESHNESS_MAP = {"day": "qdr:d", "week": "qdr:w", "month": "qdr:m", "year": "qdr:y"}


class SerpApiSearchProvider(SearchProvider):
    name = "serpapi"

    def __init__(self):
        self._api_key = os.environ.get("SERPAPI_API_KEY", "")

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def search(
        self,
        query: str,
        location: str = "New Zealand",
        freshness: str | None = None,
        max_results: int = 10,
    ) -> list[SearchResult]:
        if not self.is_configured():
            print("[search/serpapi] SERPAPI_API_KEY not set -- skipping (no results fabricated).")
            return []

        params = {
            "engine": "google",
            "q": query,
            "location": location,
            "gl": "nz",
            "num": min(max_results, 20),
            "api_key": self._api_key,
        }
        if freshness in _FRESHNESS_MAP:
            params["tbs"] = _FRESHNESS_MAP[freshness]

        try:
            resp = requests.get(API_URL, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            print(f"[search/serpapi] request failed for query {query!r}: {e}")
            return []
        except ValueError as e:
            print(f"[search/serpapi] invalid JSON response for query {query!r}: {e}")
            return []

        if "error" in data:
            print(f"[search/serpapi] provider error for query {query!r}: {data['error']}")
            return []

        results = []
        for item in data.get("organic_results", []) or []:
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("link", ""),
                    price=None,
                    currency="NZD",
                    source="web_search:serpapi",
                    description=item.get("snippet", ""),
                    condition="unknown",
                    is_sold=False,
                )
            )
        return results
