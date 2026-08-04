"""
Scraper for Thorntons Auctions (thorntons.net.nz).

Thorntons' homepage server-renders a list of "Current Auctions" cards, each
linking to /auctions/detail/<id>. We match on that URL pattern rather than a
specific CSS class, since class names are more likely to change than the
URL structure -- if Thorntons redesigns the site, this is the first thing
to re-check.
"""
import re
from typing import List, Dict

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.thorntons.net.nz"
DETAIL_PATTERN = re.compile(r"/auctions/detail/")


def fetch_listings(user_agent: str) -> List[Dict]:
    listings = []
    try:
        resp = requests.get(BASE_URL, headers={"User-Agent": user_agent}, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[thorntons] fetch failed: {e}")
        return listings

    soup = BeautifulSoup(resp.text, "lxml")
    seen_urls = set()

    for link in soup.find_all("a", href=DETAIL_PATTERN):
        href = link.get("href", "")
        url = href if href.startswith("http") else BASE_URL + href
        if url in seen_urls:
            continue
        seen_urls.add(url)

        title = link.get("title") or link.get_text(strip=True)
        if not title:
            continue

        # Description text: look at the nearest ancestor block that also
        # contains a heading, and pull its full text as loose context.
        container = link.find_parent(["div", "article", "section"]) or link.parent
        description = container.get_text(" ", strip=True) if container else ""

        listings.append({
            "source": "Thorntons",
            "title": title,
            "url": url,
            "close_date": "",  # embedded in description text; parse manually if needed
            "description": description[:1500],
        })

    return listings
