"""
Scraper for Turners' VEHICLE divisions -- Cars, Trucks & Machinery,
Motorcycles & Scooters, Buses/Caravans/Motorhomes. These are a genuinely
different part of the site from General Goods (scanner/scrapers/
turners_catalog.py): different base URLs, different template (Year/Make/
Model titles, Odometer with a unit, "BUY NOW $X" as well as bid prices).

This was built from a smaller sample of real page text than the General
Goods catalog scraper, so treat it as less battle-tested -- if a division
returns 0 results, check the regexes below against a fresh fetch of that
division's search page before assuming something else is wrong.
"""
import re
import time
from typing import Dict, List

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.turners.co.nz"

# Each division has its own base search path. `category` is an optional
# query filter (confirmed working for Trucks & Machinery as
# ?category=tractors -- other divisions may use a different param name or
# none at all; test and adjust if a division comes back empty).
DIVISIONS = {
    "Cars": {"path": "/Cars/Used-Cars-for-Sale/", "category": None},
    "Trucks & Machinery": {"path": "/Trucks-Machinery/Used-Trucks-and-Machinery-for-Sale/", "category": None},
    "Motorbikes": {"path": "/motorcycles-scooters/Used-Motorbikes-for-Sale/", "category": None},
    "Trailers & Caravans": {"path": "/buses-caravans/Used-Caravans-and-Motorhomes-for-Sale/", "category": None},
}

ITEM_URL_PATTERN = re.compile(r"/(\d{5,})/?$")  # vehicle detail URLs end in a numeric ID

_PRICE_RE = re.compile(r"(Current Bid|Starting Bid)\s*\$?([\d,]+)")
_BUY_NOW_RE = re.compile(r"BUY NOW\s*\$?([\d,]+)")
_ODOMETER_RE = re.compile(r"Odometer\s*([\d,]+)\s*(km|hr)")
_LOCATION_RE = re.compile(r"Location\s*([A-Za-z0-9 &\-,]+?)(?:Odometer|Category|Online Auction|Email Consultant|View|\Z)")


def _parse_vehicle_container(container_text: str) -> Dict:
    price, price_type = None, None
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

    odometer = ""
    om = _ODOMETER_RE.search(container_text)
    if om:
        odometer = f"{om.group(1)} {om.group(2)}"

    location_m = _LOCATION_RE.search(container_text)
    location = location_m.group(1).strip() if location_m else ""

    return {
        "price": price,
        "price_type": price_type,
        "buy_now_price": buy_now_price,
        "odometer": odometer,
        "location": location,
    }


def fetch_division(division_name: str, user_agent: str) -> List[Dict]:
    config = DIVISIONS.get(division_name)
    if not config:
        return []

    url = BASE_URL + config["path"]
    if config.get("category"):
        url += f"?category={config['category']}"

    items = []
    try:
        resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[turners_vehicles] fetch failed for '{division_name}': {e}")
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
            continue
        seen_ids.add(item_id)

        container = link.find_parent(["div", "li", "article"]) or link.parent
        container_text = container.get_text(" ", strip=True) if container else ""
        if "Odometer" not in container_text:
            grandparent = container.find_parent(["div", "li", "article"]) if container else None
            if grandparent:
                container_text = grandparent.get_text(" ", strip=True)

        parsed = _parse_vehicle_container(container_text)

        items.append({
            "source": "Turners",
            "title": title,
            "url": item_url,
            "item_id": item_id,
            "subcategory": division_name,
            "reserve_status": "",
            "closing_date": "",
            **parsed,
        })

    return items


def fetch_all_divisions(division_names: List[str], user_agent: str, request_delay: float = 2.0) -> List[Dict]:
    all_items = []
    for name in division_names:
        all_items.extend(fetch_division(name, user_agent))
        time.sleep(request_delay)
    return all_items
