"""
Facebook Marketplace has no public API and actively blocks automated
scraping (login wall + anti-bot measures), so this module does NOT fetch
anything -- it just builds a ready-to-click search URL so you can do a
30-second manual comparable check on flagged listings.
"""
from urllib.parse import quote


def marketplace_search_url(keyword: str, location: str = "") -> str:
    query = quote(keyword)
    url = f"https://www.facebook.com/marketplace/search/?query={query}"
    return url
