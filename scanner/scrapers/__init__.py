from . import thorntons, turners, mainland_auctions

SCRAPERS = {
    "thorntons": thorntons.fetch_listings,
    "turners": turners.fetch_listings,
    "mainland_auctions": mainland_auctions.fetch_listings,
}
