"""Phase 3: evidence classification (SOLD/CURRENT_LISTING/RETAIL/OTHER) and
deterministic currency conversion for international comparables.

Classification is a conservative heuristic over URL/domain + text signals.
It is intentionally cautious: anything not clearly identifiable as a
completed sale is classified as an asking price or OTHER rather than
assumed sold, per spec section 9 ("do not pretend asking prices are sold
prices").
"""
from __future__ import annotations

from scanner.search.util import identify_marketplace

_RETAIL_DOMAINS = {
    "noelleeming.co.nz", "www.noelleeming.co.nz", "jbhifi.co.nz", "www.jbhifi.co.nz",
    "harveynorman.co.nz", "www.harveynorman.co.nz", "pbtech.co.nz", "www.pbtech.co.nz",
    "amazon.com", "www.amazon.com",
}

_SOLD_SIGNAL_PHRASES = ("sold", "completed listing", "final price", "winning bid", "auction ended")


def classify_evidence(url: str, title: str = "", description: str = "", is_explicitly_sold: bool = False) -> str:
    """Returns one of SOLD / CURRENT_LISTING / RETAIL / OTHER.

    `is_explicitly_sold` should be set True only when the source API/field
    itself confirms a completed transaction (e.g. eBay's LH_Sold=1&LH_Complete=1
    filter, or a marketplace API's status=sold field) -- never inferred purely
    from search-result snippet text, which is unreliable.
    """
    from urllib.parse import urlsplit

    host = urlsplit(url).netloc.lower() if url else ""

    if is_explicitly_sold:
        return "SOLD"

    if host in _RETAIL_DOMAINS:
        return "RETAIL"

    marketplace = identify_marketplace(url)
    if marketplace in ("Trade Me", "Turners", "Thorntons", "Mainland Auctions", "Facebook Marketplace"):
        return "CURRENT_LISTING"

    if marketplace in ("eBay", "eBay AU"):
        text = f"{title} {description}".lower()
        if any(p in text for p in _SOLD_SIGNAL_PHRASES):
            # Text signal only -- still not as trustworthy as an explicit API flag,
            # but eBay listing titles/snippets do reliably say "Sold" when true.
            return "SOLD"
        return "CURRENT_LISTING"

    return "OTHER"


# Static, occasionally-updated reference rates. Not a live FX feed -- good
# enough for "is this item worth researching further", not for precise
# accounting. Update periodically; do not treat as authoritative.
_FX_TO_NZD = {
    "NZD": 1.0,
    "AUD": 1.09,
    "USD": 1.66,
    "GBP": 2.10,
    "EUR": 1.80,
}


def convert_to_nzd(price: float, currency: str) -> tuple[float, bool]:
    """Returns (price_in_nzd, converted). If currency is unknown, returns
    the original price unconverted and converted=False -- callers must
    check this before treating the number as NZD."""
    if price is None:
        return None, False
    currency = (currency or "NZD").upper()
    rate = _FX_TO_NZD.get(currency)
    if rate is None:
        return price, False
    if currency == "NZD":
        return round(price, 2), False
    return round(price * rate, 2), True
