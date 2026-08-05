from . import thorntons, mainland_auctions

SCRAPERS = {
    "thorntons": thorntons.fetch_listings,
    "mainland_auctions": mainland_auctions.fetch_listings,
}
