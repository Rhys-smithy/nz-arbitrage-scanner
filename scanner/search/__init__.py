"""Modular search abstraction layer (Phase 2B).

Every source (auction scrapers, eBay sold-listing links, permitted web
search, marketplace link-builders) implements the ``SearchSource``
interface in ``base.py`` and returns a list of ``SearchResult``. The rest
of the application only ever deals with ``SearchResult`` objects, so new
sources can be added/enabled/disabled independently without touching
downstream valuation/scoring code.
"""
from scanner.search.base import SearchResult, SearchSource

__all__ = ["SearchResult", "SearchSource"]
