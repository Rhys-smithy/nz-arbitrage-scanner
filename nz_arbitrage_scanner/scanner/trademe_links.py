"""
Trade Me comparable-pricing helper.

IMPORTANT: As of 2026, Trade Me restricts API registration to approved
in-trade/commercial sellers -- their developer terms explicitly exclude
personal or non-commercial use (casual selling, price monitoring, or
buyer-side tools like this one). So this module does NOT call the Trade Me
API. Instead, like the Facebook Marketplace helper, it just builds a
ready-to-tap search URL so you can do a quick manual comparable check on
any flagged listing.
"""
from urllib.parse import quote


def trademe_search_url(keyword: str) -> str:
    return f"https://www.trademe.co.nz/a/search?search_string={quote(keyword)}"
