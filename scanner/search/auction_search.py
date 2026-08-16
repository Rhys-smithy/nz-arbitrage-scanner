"""Wraps the EXISTING, working auction scrapers as a SearchSource.

This does not replace Turners/Thorntons/Mainland scraping -- it adapts
their existing (differently-shaped) return values into SearchResult so
the rest of Phase 2 can treat "an auction listing" and "a web search hit"
uniformly. The original scraper functions and main.py's existing pipeline
are untouched.
"""
from __future__ import annotations

from scanner.search.base import SearchResult, SearchSource
from scanner.scrapers import turners_catalog, turners_vehicles, thorntons, mainland_auctions


def _turners_item_to_result(item: dict) -> SearchResult:
    price = item.get("price") or item.get("buy_now_price")
    return SearchResult(
        title=item.get("title", ""),
        url=item.get("url", ""),
        price=price,
        currency="NZD",
        source="Turners",
        location=item.get("location", ""),
        description=item.get("subcategory", ""),
        condition=item.get("condition", "unknown"),
        is_sold=False,  # live/asking auction price, not a completed sale
    )


def _turners_vehicle_item_to_result(item: dict) -> SearchResult:
    """Same shape as _turners_item_to_result but for turners_vehicles.py's
    slightly different item dict (odometer instead of a condition field,
    subcategory is the division name rather than a General Goods category)."""
    price = item.get("price") or item.get("buy_now_price")
    description = item.get("subcategory", "")
    odometer = item.get("odometer")
    if odometer:
        description = f"{description} - Odometer: {odometer}" if description else f"Odometer: {odometer}"
    return SearchResult(
        title=item.get("title", ""),
        url=item.get("url", ""),
        price=price,
        currency="NZD",
        source="Turners",
        location=item.get("location", ""),
        description=description,
        condition=item.get("condition", "unknown"),
        is_sold=False,
    )


def _blurb_item_to_result(item: dict, source_name: str) -> SearchResult:
    return SearchResult(
        title=item.get("title", ""),
        url=item.get("url", ""),
        price=None,  # Thorntons/Mainland bidding is JS-only -- no real price available
        currency="NZD",
        source=source_name,
        description=item.get("description", ""),
        condition="unknown",
        is_sold=False,
    )


class AuctionSearchSource(SearchSource):
    """Adapts Turners/Thorntons/Mainland scrapers into SearchResult objects.

    Each underlying site can still be toggled independently via
    config["sites"] / config["turners_categories"] exactly as before --
    this class just reshapes what they already return.
    """

    name = "auction"
    available = True

    def __init__(self, config: dict):
        self.config = config

    def search(self, query: str = "", **kwargs) -> list[SearchResult]:
        results: list[SearchResult] = []
        user_agent = self.config.get("user_agent", "")
        delay = self.config.get("request_delay_seconds", 2.0)

        categories = kwargs.get("turners_categories", self.config.get("turners_categories", []))
        for category in categories:
            if category in turners_vehicles.DIVISIONS:
                try:
                    items = turners_vehicles.fetch_all_divisions([category], user_agent, delay)
                except Exception:
                    items = []
                results.extend(_turners_vehicle_item_to_result(i) for i in items)
            else:
                try:
                    items = turners_catalog.fetch_all_categories(category, user_agent, delay)
                except Exception:
                    items = []
                results.extend(_turners_item_to_result(i) for i in items)

        sites = self.config.get("sites", {})
        if sites.get("thorntons"):
            try:
                results.extend(
                    _blurb_item_to_result(i, "Thorntons") for i in thorntons.fetch_listings(user_agent)
                )
            except Exception:
                pass
        if sites.get("mainland_auctions"):
            try:
                results.extend(
                    _blurb_item_to_result(i, "Mainland Auctions")
                    for i in mainland_auctions.fetch_listings(user_agent)
                )
            except Exception:
                pass
        return results
