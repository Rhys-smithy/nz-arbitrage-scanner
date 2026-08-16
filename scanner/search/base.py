"""Common result type and source interface for the search abstraction layer.

Design note: this repo already has working, permitted data collection
(Turners catalog/vehicle scrapers with real prices, Thorntons/Mainland
blurb scrapers, eBay/TradeMe/Facebook *link builders*). Phase 2B does not
replace any of that -- it normalises all of it into one shape
(``SearchResult``) so valuation/scoring code written after this point
never needs to know which source produced a result.

No source in this layer bypasses CAPTCHAs, authentication, bot detection,
or robots/access controls. Sources that cannot legally/technically fetch
real data (e.g. web search without an API key configured) return an empty
list and set ``available=False`` rather than fabricating results.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class SearchResult:
    """Normalised shape every search source must return.

    ``price`` is an *asking* price unless ``is_sold`` is True, in which
    case it is an observed transaction price -- callers (comparable
    research, valuation) must check ``is_sold`` before treating a price as
    evidence of achieved value versus merely an ask.
    """

    title: str
    url: str
    price: Optional[float]
    currency: str
    source: str
    location: str = ""
    description: str = ""
    image_url: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    condition: str = "unknown"
    is_sold: bool = False  # True only for confirmed completed/sold transactions

    # Phase 4B follow-up (post Turners-direct-discovery live validation):
    # minimum useful auction-state metadata, sourced only from what
    # scanner/scrapers/turners_catalog.py and turners_vehicles.py already
    # parse -- nothing here is invented or estimated. All optional/defaulted
    # so every existing source (Tavily/SerpAPI/Brave, Thorntons/Mainland
    # blurbs) and every existing SearchResult(...) call site keeps working
    # unchanged; they simply never populate these and get the defaults below.
    #
    # price_type distinguishes what `price` actually IS: "current_bid" (real
    # bidding has happened), "starting_bid" (the seller's opening number,
    # zero bids placed), "buy_now" (a fixed, immediately-payable price), or
    # None (unknown / non-Turners source, e.g. a Tavily snippet with a
    # text-extracted price and no structured auction state at all).
    price_type: Optional[str] = None
    buy_now_price: Optional[float] = None
    # "Reserve Met" / "No Reserve" / "Reserve Not Met" / None (General Goods
    # only -- Turners' vehicle division pages don't expose this, so vehicle
    # candidates always carry None here; that is itself meaningful signal,
    # not missing data).
    reserve_status: Optional[str] = None
    closing_date: str = ""
    starts_on: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "price": self.price,
            "currency": self.currency,
            "source": self.source,
            "location": self.location,
            "description": self.description,
            "image_url": self.image_url,
            "timestamp": self.timestamp,
            "condition": self.condition,
            "is_sold": self.is_sold,
            "price_type": self.price_type,
            "buy_now_price": self.buy_now_price,
            "reserve_status": self.reserve_status,
            "closing_date": self.closing_date,
            "starts_on": self.starts_on,
        }


class SearchSource:
    """Interface every search source implements.

    ``name`` must be unique and match the key used in config's
    ``search_sources`` toggle map so sources can be enabled/disabled
    independently.
    """

    name: str = "base"
    available: bool = True  # False if source has no credentials/API configured

    def search(self, query: str, **kwargs) -> list[SearchResult]:
        raise NotImplementedError
