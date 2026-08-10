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
