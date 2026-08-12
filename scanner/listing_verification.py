"""Phase 4B.1: listing verification.

Core rule (per the user-approved 4B.1 scope): a discovery candidate's price
and condition must never be trusted from Tavily's search-snippet text alone.
Before any AI/valuation work touches a candidate, this module re-fetches its
actual authoritative source -- reusing the exact same request pattern
(requests + BeautifulSoup + the configured User-Agent/request delay) already
established in scanner/scrapers/ and scanner/item_detail.py -- and returns a
VerifiedListing that scanner/discover.py must check before letting a
candidate reach identify_product/research_comparables/valuation/scoring.

Source coverage decided during the 4B.1 spike (read-only investigation
against live pages + robots.txt, no code changes at the time):

- Turners General Goods: full verification. The item's own detail page
  reliably has condition (already proven by scanner/item_detail.py) but
  NOT price -- confirmed live, price simply isn't in that page's static
  HTML (General Goods items are run as Trade Me-backed auctions under the
  hood). Price comes from the category/subcategory catalog page instead,
  reusing scanner/scrapers/turners_catalog.fetch_category_items() and
  matching the row by item_id.

- Turners Vehicles: full verification. Confirmed live that a fixed "BuyNow"
  vehicle (Cars division) DOES show price on its own detail page, but an
  auction-style ("Starting Bid"/"Current Bid") vehicle's detail page shows
  NO price at all (same limitation as General Goods) -- confirmed against a
  live Trucks & Machinery listing. So: try the detail page's own price
  first (handles BuyNow, discounted or not), and fall back to the
  division's catalog page (reusing turners_vehicles.fetch_division(),
  matched by item_id) when the detail page has none. Tender-style listings
  (also seen live in Trucks & Machinery) never publish a price anywhere and
  correctly fall through to "unavailable".

- Trade Me: unsupported, no HTTP request ever made. trademe.co.nz/robots.txt
  has a single global `User-agent: *` block with `Disallow: /a/*listing/`
  and no carve-out for Marketplace listings (the only "listing" exceptions
  are /a/services/, /a/jobs/, /a/property/) -- so a compliant fetch of an
  individual Trade Me listing page is not possible. The Trade Me API
  (scanner/trademe_api.py) is separately excluded from personal/buyer-side
  use per scanner/trademe_links.py. Both are access restrictions, not
  missing code -- do not bypass either.

- Thorntons / Mainland Auctions: unsupported, no HTTP request ever made.
  Both are JS-only bidding platforms with no server-rendered per-lot price
  (see README.md/CLAUDE.md); the URLs discovery matches for these
  (/auctions/detail/<id>, /auctions/<slug>) are auction-EVENT pages, not
  per-item pages, so there is no authoritative per-item price to fetch even
  in principle. Liveness-only is explicitly NOT sufficient for a scored
  opportunity (per 4B.1 scope) -- no workaround is implemented here.
"""
from __future__ import annotations

import re
import time
from typing import Optional
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

from scanner.item_detail import fetch_item_detail
from scanner.models import VerifiedListing
from scanner.scrapers.turners_catalog import fetch_category_items
from scanner.scrapers.turners_vehicles import DIVISIONS, fetch_division
from scanner.search.util import identify_marketplace

# Matches Turners General Goods item detail URLs, e.g.
# /General-Goods/Search/electronics/cameras--equipment/28374370/
# Capturing category, subcategory, and item_id -- the category/subcategory
# pair is exactly the slug fetch_category_items() expects.
_GENERAL_GOODS_ITEM_RE = re.compile(
    r"/General-Goods/Search/([a-z0-9\-]+)/([a-z0-9\-]+)/(\d+)/?$", re.IGNORECASE
)

# Vehicle detail URLs end in a numeric id (shared shape across all
# divisions -- same pattern turners_vehicles.py itself uses).
_VEHICLE_ITEM_RE = re.compile(r"/(\d{5,})/?$")

# Reverse lookup: URL path prefix -> division name, built directly from
# turners_vehicles.DIVISIONS so it can't drift out of sync with that module.
_VEHICLE_PATH_TO_DIVISION = {cfg["path"]: name for name, cfg in DIVISIONS.items()}

# Sources verified during the spike to have no authoritative per-item price
# obtainable through a compliant fetch. Kept as data (not scattered if/else)
# so it's obvious at a glance that no HTTP request is ever attempted for them.
_UNSUPPORTED_REASONS = {
    "Trade Me": (
        "Trade Me listing pages are disallowed by robots.txt "
        "(Disallow: /a/*listing/, no Marketplace carve-out); the API is also "
        "excluded from personal/buyer-side use (see scanner/trademe_links.py)."
    ),
    "Thorntons": (
        "Thorntons has no server-rendered per-lot price (JS-only bidding "
        "platform); the discovery URL is an auction-event page, not an "
        "individual item page."
    ),
    "Mainland Auctions": (
        "Mainland Auctions has no server-rendered per-lot price (JS-only "
        "bidding platform); the discovery URL is an auction-event page, not "
        "an individual item page."
    ),
}

# Vehicle detail-page price parser. Confirmed live against a discounted
# BuyNow listing (text collapses via BeautifulSoup get_text(" ", strip=True)
# to "...BuyNow Was $18,900 You Save $1,500 $17,400 *All On Road Costs...");
# the plain/non-discounted BuyNow fallback below was NOT confirmed against a
# live example during the spike (every BuyNow listing sampled happened to be
# discounted) -- it's a reasonable inference from the same "BuyNow $X"
# shape, but if it's ever wrong it fails safe: it simply won't match, price
# stays None, and the caller falls back to the division catalog page rather
# than reporting a wrong number.
_VEHICLE_WAS_SAVE_PRICE_RE = re.compile(
    r"Was\s*\$([\d,]+(?:\.\d+)?)\s*You Save\s*\$([\d,]+(?:\.\d+)?)\s*\$([\d,]+(?:\.\d+)?)"
)
_VEHICLE_PLAIN_BUYNOW_RE = re.compile(r"BuyNow\s*\$([\d,]+(?:\.\d+)?)", re.IGNORECASE)

# Condition-ish labels seen on live Turners vehicle detail pages. Cars-division
# pages carry no explicit condition labels at all (only free-text Comments);
# Trucks & Machinery pages add Cab/Interior/Mechanical Condition. Extraction
# below looks for whichever of these are actually present rather than
# assuming all vehicle pages share one shape.
_VEHICLE_CONDITION_LABELS = [
    "Cab Condition", "Interior Condition", "Mechanical Condition", "Comments",
]
_VEHICLE_CONDITION_BOUNDARY_LABELS = _VEHICLE_CONDITION_LABELS + [
    "Viewing Times", "Contact & Auction Details", "Additional Information",
    "Contact & Location", "Machinery Details", "All Vehicle Features",
]


def _extract_vehicle_condition(detail_text: str) -> str:
    """Best-effort extraction of whichever condition-ish labels are present
    on a Turners vehicle detail page. Mirrors scanner/item_detail.py's
    label-boundary approach (regex over text, not tag structure -- more
    resilient to minor markup differences) but tolerates labels being
    partially absent, since Cars and Trucks & Machinery pages don't share
    one fixed set of fields (confirmed live during the 4B.1 spike)."""
    if not detail_text:
        return ""
    parts = []
    for label in _VEHICLE_CONDITION_LABELS:
        others = [l for l in _VEHICLE_CONDITION_BOUNDARY_LABELS if l != label]
        boundary = "|".join(re.escape(l) for l in others)
        pattern = rf"{re.escape(label)}\s*\n+\s*(.+?)(?:\n+(?:{boundary})|\Z)"
        m = re.search(pattern, detail_text, re.DOTALL)
        if m:
            value = " ".join(m.group(1).split())[:500]
            if value:
                parts.append(f"{label}: {value}")
    return "; ".join(parts)


def _detail_page_price(detail_text: str) -> Optional[float]:
    if not detail_text:
        return None
    m = _VEHICLE_WAS_SAVE_PRICE_RE.search(detail_text)
    if m:
        try:
            return float(m.group(3).replace(",", ""))
        except ValueError:
            return None
    m = _VEHICLE_PLAIN_BUYNOW_RE.search(detail_text)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def _vehicle_division_for_path(path: str) -> Optional[str]:
    for prefix, name in _VEHICLE_PATH_TO_DIVISION.items():
        if path.startswith(prefix):
            return name
    return None


class VerificationCache:
    """Per-run cache of Turners catalog/division page fetches, so multiple
    discovery candidates that land in the same General Goods subcategory or
    the same vehicle division only trigger one fetch of that page instead of
    one per candidate -- avoiding unnecessary repeated requests without
    building anything more elaborate than this module needs (discovery caps
    candidates at max_research_items, single digits per run)."""

    def __init__(self, user_agent: str, request_delay: float = 2.0):
        self.user_agent = user_agent
        self.request_delay = request_delay
        self._general_goods: dict[str, list] = {}
        self._vehicles: dict[str, list] = {}

    def general_goods_items(self, slug: str) -> list:
        if slug not in self._general_goods:
            self._general_goods[slug] = fetch_category_items(slug, self.user_agent)
            time.sleep(self.request_delay)
        return self._general_goods[slug]

    def vehicle_items(self, division: str) -> list:
        if division not in self._vehicles:
            self._vehicles[division] = fetch_division(division, self.user_agent)
            time.sleep(self.request_delay)
        return self._vehicles[division]


def _verify_turners_general_goods(url: str, cache: VerificationCache) -> VerifiedListing:
    match = _GENERAL_GOODS_ITEM_RE.search(urlsplit(url).path)
    if not match:
        return VerifiedListing(status="unavailable", reason="URL doesn't match a General Goods item page shape")
    category, subcategory, item_id = match.groups()
    slug = f"{category}/{subcategory}"

    detail = fetch_item_detail(url, cache.user_agent)
    time.sleep(cache.request_delay)
    condition_text = "; ".join(
        f"{label}: {detail[key]}"
        for label, key in (("Condition", "condition"), ("Testing Level", "testing_level"),
                            ("Quantity", "quantity"), ("Comments", "comments"))
        if detail.get(key)
    )

    catalog_items = cache.general_goods_items(slug)
    row = next((i for i in catalog_items if i.get("item_id") == item_id), None)

    if row is None:
        return VerifiedListing(
            status="unavailable",
            condition_text=condition_text,
            reason=(
                f"Item {item_id} not found on page 1 of /General-Goods/Search/{slug}/ "
                "-- may be off page 1, closed, or removed. Treated as unable to verify, "
                "not confirmed dead."
            ),
            raw_fields={"category": category, "subcategory": subcategory},
        )

    price = row.get("price") if row.get("price") is not None else row.get("buy_now_price")
    if row.get("pricing_status") != "priced" or price is None:
        return VerifiedListing(
            status="unavailable",
            condition_text=condition_text,
            reason=f"No authoritative price available (pricing_status={row.get('pricing_status')!r}).",
            raw_fields=row,
        )

    return VerifiedListing(
        status="verified", price=price, condition_text=condition_text, is_live=True, raw_fields=row,
    )


def _verify_turners_vehicle(url: str, cache: VerificationCache) -> VerifiedListing:
    path = urlsplit(url).path
    match = _VEHICLE_ITEM_RE.search(path)
    if not match:
        return VerifiedListing(status="unavailable", reason="URL doesn't match a vehicle item page shape")
    item_id = match.group(1)

    division = _vehicle_division_for_path(path)
    if division is None:
        return VerifiedListing(
            status="unavailable", reason=f"Path {path!r} doesn't match any known Turners vehicle division"
        )

    detail_text = ""
    try:
        resp = requests.get(url, headers={"User-Agent": cache.user_agent}, timeout=20)
        resp.raise_for_status()
        detail_text = BeautifulSoup(resp.text, "lxml").get_text("\n", strip=True)
    except requests.RequestException as e:
        print(f"[listing_verification] vehicle detail fetch failed for {url}: {e}")
    time.sleep(cache.request_delay)

    condition_text = _extract_vehicle_condition(detail_text)
    price = _detail_page_price(detail_text)
    row = None

    if price is None:
        # Starting Bid / Current Bid / Tender vehicles carry no price on
        # their own detail page (confirmed live during the 4B.1 spike) --
        # fall back to the division catalog page, same mechanism as
        # General Goods.
        catalog_items = cache.vehicle_items(division)
        row = next((i for i in catalog_items if i.get("item_id") == item_id), None)
        if row is not None:
            price = row.get("price") if row.get("price") is not None else row.get("buy_now_price")

    if price is None:
        return VerifiedListing(
            status="unavailable",
            condition_text=condition_text,
            reason=(
                "No authoritative price on the detail page or division catalog "
                "(Tender-style listings never publish a price; the item may also "
                "be off page 1 of the catalog, closed, or removed)."
            ),
            raw_fields=row or {"division": division},
        )

    return VerifiedListing(
        status="verified",
        price=price,
        condition_text=condition_text,
        is_live=True,
        raw_fields=row or {"division": division},
    )


def verify_listing(url: str, cache: VerificationCache) -> VerifiedListing:
    """Dispatch a single discovery candidate URL to the right verifier.

    Never fetches anything for a source listed in _UNSUPPORTED_REASONS --
    those return status="unsupported" immediately, with no HTTP request.
    """
    marketplace = identify_marketplace(url)

    if marketplace in _UNSUPPORTED_REASONS:
        return VerifiedListing(status="unsupported", reason=_UNSUPPORTED_REASONS[marketplace])

    if marketplace == "Turners":
        path = urlsplit(url).path
        if _GENERAL_GOODS_ITEM_RE.search(path):
            return _verify_turners_general_goods(url, cache)
        if _vehicle_division_for_path(path) is not None:
            return _verify_turners_vehicle(url, cache)
        return VerifiedListing(
            status="unavailable", reason=f"Turners URL path {path!r} doesn't match a known item shape"
        )

    return VerifiedListing(status="unsupported", reason=f"No verifier implemented for source {marketplace!r}")
