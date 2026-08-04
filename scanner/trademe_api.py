"""
Thin wrapper around the Trade Me public Search API, used to gauge demand and
typical asking prices for a keyword/category as a comparable-value signal.

SETUP REQUIRED:
1. Register a free developer account at https://developer.trademe.co.nz
2. Create an application to get an OAuth consumer key
3. Paste that key into config.json as "trademe_api_key"

NOTE: Trade Me's API details (auth scheme, endpoint paths, response fields)
can change over time and this was written without the ability to test live
against the API. If calls start failing, check the current docs at
https://developer.trademe.co.nz/api-reference/ and adjust `BASE_URL` /
`_get` below accordingly -- the rest of the scanner doesn't need to change.
"""
import statistics
import time
from typing import Dict, List, Optional

import requests

BASE_URL = "https://api.trademe.co.nz/v1"


class TradeMeClient:
    def __init__(self, consumer_key: str, user_agent: str, request_delay: float = 2.0):
        self.consumer_key = consumer_key
        self.user_agent = user_agent
        self.request_delay = request_delay
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def _get(self, path: str, params: Dict) -> Optional[dict]:
        if not self.consumer_key or "PASTE_YOUR" in self.consumer_key:
            return None  # not configured yet
        params = dict(params)
        params["oauth_consumer_key"] = self.consumer_key
        try:
            resp = self.session.get(f"{BASE_URL}{path}", params=params, timeout=15)
            time.sleep(self.request_delay)
            if resp.status_code != 200:
                return None
            return resp.json()
        except (requests.RequestException, ValueError):
            return None

    def search_comparables(self, keyword: str, rows: int = 30) -> Dict:
        """Search current Trade Me listings for a keyword and summarise pricing.

        Returns dict: {count, median_price, min_price, max_price, search_url}
        even when the API call fails, so the report always has a usable
        fallback link for a manual check.
        """
        search_url = f"https://www.trademe.co.nz/a/search?search_string={keyword.replace(' ', '%20')}"
        result = {
            "count": 0,
            "median_price": None,
            "min_price": None,
            "max_price": None,
            "search_url": search_url,
        }

        data = self._get("/Search/General.json", {
            "search_string": keyword,
            "rows": rows,
            "sort_order": "PriceAsc",
        })
        if not data or "List" not in data:
            return result

        prices = []
        for listing in data.get("List", []):
            price = listing.get("BuyNowPrice") or listing.get("PriceDisplay")
            if isinstance(price, (int, float)) and price > 0:
                prices.append(price)

        result["count"] = data.get("TotalCount", len(data.get("List", [])))
        if prices:
            result["median_price"] = round(statistics.median(prices), 2)
            result["min_price"] = min(prices)
            result["max_price"] = max(prices)
        return result
