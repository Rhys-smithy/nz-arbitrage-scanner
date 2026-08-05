"""
Scraper for Turners' General Goods CATALOG search (not the auction event
pages -- see scanner/scrapers/turners.py for those, which are JS-loaded).

This hits https://www.turners.co.nz/General-Goods/Search/<category-slug>/
which -- unlike the auction event pages -- IS server-rendered with real
per-item data: title, current/starting bid price, reserve status, location,
subcategory, and closing date. This is where genuine price comparison
becomes possible.

Only fetches page 1 of each category (~20 items) per run. Combined with the
seen-listings cache in scanner/store.py, new items naturally surface over
repeated runs without needing to handle pagination (which appeared to be
JS-driven based on how the site's page-2+ links were rendered).
"""
import re
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.turners.co.nz"
ITEM_URL_PATTERN = re.compile(r"/General-Goods/Search/[a-z0-9\-]+/[a-z0-9\-]+/(\d+)/?$")

# Maps our category names to the real Turners General Goods category slugs
# (confirmed against https://www.turners.co.nz/General-Goods/Search/ )
CATEGORY_SLUGS = {
    "Electronics & Tech": ["electronics", "computer", "gaming"],
    "Machinery & Tools": ["machinery"],
    "Sport & Leisure": ["sport--leisure"],
    "Jewellery & Watches": ["jewellery"],
    "Toys & Games": ["toys"],
    "House & Garden": ["house--garden"],
    "Health & Beauty": ["health--beauty"],
    "Antiques & Collectables": ["antiques", "art", "crafts"],
    "Clothing": ["clothing"],
    "Automotive Parts": ["automotive-goods"],
}

_PRICE_RE = re.compile(r"(Current Bid|Starting Bid)\s*\$?([\d,]+)")
_BUY_NOW_RE = re.compile(r"BUY NOW\s*\$?([\d,]+)")
_RESERVE_RE = re.compile(r"(Reserve Met|No Reserve|Reserve Not Met)")
_CLOSES_RE = re.compile(r"Closes On\s*([0-9]{1,2} [A-Za-z]{3} \d{2})")
_LOCATION_RE = re.compile(r"Location\s*([A-Za-z0-9 &\-,]+?)(?:Odometer|Category)")
_CATEGORY_RE = re.compile(r"Category\s*([A-Za-z0-9 &\->,]+?)(?:Online Auction|Email Consultant|$)")


def _parse_item_container(container_text: str) -> Dict:
    price = None
    price_type = None
    m = _PRICE_RE.search(container_text)
    if m:
        price_type = "current_bid" if m.group(1) == "Current Bid" else "starting_bid"
        try:
            price = float(m.group(2).replace(",", ""))
        except ValueError:
            price = None

    buy_now_price = None
    bn = _BUY_NOW_RE.search(container_text)
    if bn:
        try:
            buy_now_price = float(bn.group(1).replace(",", ""))
        except ValueError:
            buy_now_price = None

    reserve_m = _RESERVE_RE.search(container_text)
    reserve_status = reserve_m.group(1) if reserve_m else None

    closes_m = _CLOSES_RE.search(container_text)
    closing_date = closes_m.group(1) if closes_m else ""

    location_m = _LOCATION_RE.search(container_text)
    location = location_m.group(1).strip() if location_m else ""

    category_m = _CATEGORY_RE.search(container_text)
    subcategory = category_m.group(1).strip() if category_m else ""

    return {
        "price": price,
        "price_type": price_type,
        "buy_now_price": buy_now_price,
        "reserve_status": reserve_status,
        "closing_date": closing_date,
        "location": location,
        "subcategory": subcategory,
    }


def fetch_category_items(slug: str, user_agent: str) -> List[Dict]:
    """Fetch page 1 of a Turners General Goods category catalog."""
    url = f"{BASE_URL}/General-Goods/Search/{slug}/"
    items = []
    try:
        resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[turners_catalog] fetch failed for '{slug}': {e}")
        return items

    soup = BeautifulSoup(resp.text, "lxml")
    seen_ids = set()

    for link in soup.find_all("a", href=ITEM_URL_PATTERN):
        href = link.get("href", "")
        match = ITEM_URL_PATTERN.search(href)
        if not match:
            continue
        item_id = match.group(1)
        if item_id in seen_ids:
            continue

        item_url = href if href.startswith("http") else BASE_URL + href
        title = link.get("title") or link.get_text(strip=True)
        if not title:
            continue  # this particular <a> has no usable text (likely a thumbnail
                      # image link) -- don't mark the item_id as seen yet, so the
                      # real text link for the same item still gets processed
        seen_ids.add(item_id)

        container = link.find_parent(["div", "li", "article"]) or link.parent
        # Walk up a couple more levels if the immediate parent is too small
        # to contain the price block (structure may vary).
        container_text = container.get_text(" ", strip=True) if container else ""
        if "Current Bid" not in container_text and "Starting Bid" not in container_text:
            grandparent = container.find_parent(["div", "li", "article"]) if container else None
            if grandparent:
                container_text = grandparent.get_text(" ", strip=True)

        parsed = _parse_item_container(container_text)

        items.append({
            "source": "Turners",
            "title": title,
            "url": item_url,
            "item_id": item_id,
            **parsed,
        })

    return items


def fetch_all_categories(category_name: str, user_agent: str, request_delay: float = 2.0) -> List[Dict]:
    """Fetch all Turners slugs mapped to one of our category names."""
    import time
    all_items = []
    for slug in CATEGORY_SLUGS.get(category_name, []):
        all_items.extend(fetch_category_items(slug, user_agent))
        time.sleep(request_delay)
    return all_items
