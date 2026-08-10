"""Interface every concrete web-search API provider implements.

A provider is a thin, honest wrapper around ONE legitimate third-party
search API. It must never scrape a search engine's HTML directly, bypass
its bot protection, or fabricate results when uncredentialed/unreachable.
"""
from __future__ import annotations

from scanner.search.base import SearchResult


class SearchProvider:
    name: str = "base"

    def is_configured(self) -> bool:
        raise NotImplementedError

    def search(
        self,
        query: str,
        location: str = "New Zealand",
        freshness: str | None = None,
        max_results: int = 10,
    ) -> list[SearchResult]:
        raise NotImplementedError
