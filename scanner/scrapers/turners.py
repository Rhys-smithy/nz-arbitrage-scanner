"""
Scraper for Turners General Goods auctions (turners.co.nz/General-Goods).

Turners lists upcoming auction events in a table with links matching
/General-Goods/Auctions/<id>/. Each row also shows a branch name and lot
count as plain text near the link, which we grab as loose context.
"""
import re
from typing import List, Dict

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.turners.co.nz"
LISTING_PAGE = f"{BASE_URL}/General-Goods/"
DETAIL_PATTERN = re.compile(r"/General-Goods/Auctions/\d+-\d+/")


def fetch_listings(user_agent: str) -> List[Dict]:
    listings = []
    try:
        resp = requests.get(LISTING_PAGE, headers={"User-Agent": user_agent}, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[turners] fetch failed: {e}")
        return listings

    soup = BeautifulSoup(resp.text, "lxml")
    seen_urls = set()

    for link in soup.find_all("a", href=DETAIL_PATTERN):
        href = link.get("href", "")
        url = href if href.startswith("http") else BASE_URL + href
        if url in seen_urls:
            continue
        seen_urls.add(url)

        title = link.get_text(strip=True)
        if not title:
            continue

        # Grab the surrounding row/list-item text for branch + lot count +
        # closing date context.
        container = link.find_parent(["tr", "li", "div"]) or link.parent
        description = container.get_text(" ", strip=True) if container else ""

        listings.append({
            "source": "Turners",
            "title": title,
            "url": url,
            "close_date": "",  # date text is present in `description`; parse if needed
            "description": description[:1500],
        })

    return listings
