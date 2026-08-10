"""Enable/disable search sources independently via config["search_sources"]."""
from __future__ import annotations

from scanner.search.auction_search import AuctionSearchSource
from scanner.search.ebay_search import EbaySearchSource
from scanner.search.marketplace_search import MarketplaceSearchSource
from scanner.search.web_search import WebSearchSource


def build_sources(config: dict) -> list:
    toggles = config.get("search_sources", {
        "auction": True,
        "ebay": True,
        "marketplace": True,
        "web_search": True,
    })
    sources = []
    if toggles.get("auction", True):
        sources.append(AuctionSearchSource(config))
    if toggles.get("ebay", True):
        sources.append(EbaySearchSource())
    if toggles.get("marketplace", True):
        sources.append(MarketplaceSearchSource())
    if toggles.get("web_search", True):
        sources.append(WebSearchSource())
    return sources
