"""
Scraper for Mainland Auctions (mainlandauctions.nz), Christchurch.

Their homepage lists "Upcoming auctions" and "Past auctions" as links to
/auctions/<slug>. Note: Mainland Auctions also lists some stock directly as
a Trade Me seller (member ID 6482428) -- see their "view online auctions"
link. If you want those included too, the Trade Me API's general search
with a member filter can pull that seller's current listings; check
https://developer.trademe.co.nz/api-reference/ for the exact parameter,
since this wasn't verified against a live call.
"""
import re
from typing import List, Dict

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.mainlandauctions.nz"
TRADEME_MEMBER_ID = "6482428"  # for optional future use, see docstring above
DETAIL_PATTERN = re.compile(r"^/auctions/[a-z0-9\-]+$")


def fetch_listings(user_agent: str) -> List[Dict]:
    listings = []
    try:
        resp = requests.get(BASE_URL, headers={"User-Agent": user_agent}, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[mainland_auctions] fetch failed: {e}")
        return listings

    soup = BeautifulSoup(resp.text, "lxml")
    seen_urls = set()

    for link in soup.find_all("a", href=True):
        href = link["href"]
        # normalise to a path-only check
        path = href if href.startswith("/") else href.replace(BASE_URL, "")
        if not DETAIL_PATTERN.match(path):
            continue

        url = BASE_URL + path if path.startswith("/") else href
        if url in seen_urls:
            continue
        seen_urls.add(url)

        title = link.get_text(strip=True)
        if not title:
            continue

        container = link.find_parent(["div", "li", "section"]) or link.parent
        description = container.get_text(" ", strip=True) if container else ""

        listings.append({
            "source": "Mainland Auctions",
            "title": title,
            "url": url,
            "close_date": "",
            "description": description[:1500],
        })

    return listings
