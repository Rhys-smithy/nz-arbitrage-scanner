"""Brave Search API provider (https://api.search.brave.com).

Legitimate, ToS-permitted API with a free tier. Requires BRAVE_API_KEY.
Never scrapes brave.com/google.com/bing.com HTML -- this only calls
Brave's documented REST API.
"""
from __future__ import annotations

import os

import requests

from scanner.search.base import SearchResult
from scanner.search.providers.base import SearchProvider

API_URL = "https://api.search.brave.com/res/v1/web/search"

# Brave's freshness param: pd=past day, pw=past week, pm=past month, py=past year
_FRESHNESS_MAP = {"day": "pd", "week": "pw", "month": "pm", "year": "py"}


class BraveSearchProvider(SearchProvider):
    name = "brave"

    def __init__(self):
        self._api_key = os.environ.get("BRAVE_API_KEY", "")

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
            print("[search/brave] BRAVE_API_KEY not set -- skipping (no results fabricated).")
            return []

        params = {
            "q": query,
            "country": "nz",
            "count": min(max_results, 20),
        }
        if freshness in _FRESHNESS_MAP:
            params["freshness"] = _FRESHNESS_MAP[freshness]

        try:
            resp = requests.get(
                API_URL,
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self._api_key,
                },
                params=params,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            print(f"[search/brave] request failed for query {query!r}: {e}")
            return []
        except ValueError as e:
            print(f"[search/brave] invalid JSON response for query {query!r}: {e}")
            return []

        results = []
        for item in (data.get("web", {}) or {}).get("results", []) or []:
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    price=None,  # search snippets don't reliably carry structured price
                    currency="NZD",
                    source="web_search:brave",
                    description=item.get("description", ""),
                    condition="unknown",
                    is_sold=False,
                )
            )
        return results
