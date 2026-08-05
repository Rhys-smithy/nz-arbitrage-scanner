"""
Builds an eBay "sold + completed listings" search URL -- the closest thing
to real comparable sale-price data available anywhere in this scanner (see
README: neither Trade Me nor Facebook Marketplace expose sold-price history
publicly, but eBay does via these URL parameters).

Uses ebay.com.au since NZ has no separate eBay site and .com.au is the more
regionally-relevant reference market than .com -- treat results as a rough
"what's this realistically worth on the wider market" signal, not a NZ
price, since Trade Me is where NZ buyers actually are.
"""
from urllib.parse import quote


def ebay_sold_search_url(keyword: str) -> str:
    query = quote(keyword)
    return f"https://www.ebay.com.au/sch/i.html?_nkw={query}&LH_Sold=1&LH_Complete=1&_sop=13"
