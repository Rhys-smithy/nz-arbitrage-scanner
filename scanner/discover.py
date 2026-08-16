"""Phase 3 section 13: Opportunity Discovery mode.

Orchestrates: generate category searches -> run web-search provider ->
dedupe -> identify products -> research comparables -> run Phase 2
valuation/cost/max-buy-price/flip-score engine (unchanged, reused as-is)
-> rank -> report -> optional Telegram alerts.

This is a NEW entry point (`python3 main.py --mode discover`), not a
replacement for the existing daily auction-scan pipeline in main(). It
does not touch scanner/store.py's seen.json (Phase 2 auction dedup) --
it has its own freshness store (scanner/discovery_store.py).
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone

from scanner.bundle import value_bundle
from scanner.comparable_research import extract_price, research_comparables
from scanner.discovery_report import update_discovery_index, write_discovery_report
from scanner.discovery_store import load_discovered, record_sightings, save_discovered
from scanner.evidence import classify_evidence
from scanner.flip_score import score_and_decide
from scanner.liquidity import estimate_liquidity
from scanner.listing_verification import VerificationCache, verify_listing
from scanner.models import Opportunity, ProductIdentification
from scanner.notifier import build_flip_alert, send_telegram_message
from scanner.product_id import detect_condition_risk, identify_product
from scanner.query_generator import allocate_discovery_queries
from scanner.researcher import research
from scanner.search.auction_search import AuctionSearchSource
from scanner.search.util import canonicalize_url, identify_marketplace, is_individual_listing_url
from scanner.search.web_search import WebSearchSource
from scanner.search_stats import (
    extract_concept_from_query,
    load_stats,
    record_query_concept_result,
    save_stats,
)
from scanner.trader import trader_review
from scanner.valuation import apply_valuation

# Opportunity discovery is NZ-local only (spec: no eBay here -- eBay stays
# usable as *comparable evidence* in comparable_research.py, a separate
# pipeline stage, but must never surface as a buyable opportunity). These
# are the domains this repo already treats as real marketplaces with a
# working individual-listing pattern in search/util.py.
#
# Thorntons/Mainland Auctions were removed from this list (source audit,
# 2026-08-16): both are confirmed JS-only bidding platforms that even
# Google can't index (see README.md), so Tavily-style search discovery
# has never found real per-lot candidates there in practice, and
# scanner/listing_verification.py has always marked anything from either
# source "unsupported" -- zero conversion, forever. Keeping them in the
# domain filter only diluted Tavily's per-query result budget away from
# domains that can actually produce a candidate. Removing them is a
# config-shaped change only: the sources themselves are untouched, still
# fully supported by the legacy scan pipeline (config.json's separate
# `sites` toggle), and still handled correctly by verify_listing() /
# discover.py's WATCH-preservation path below if a candidate from either
# ever does turn up some other way.
DEFAULT_DISCOVERY_DOMAINS = [
    "trademe.co.nz",
    "turners.co.nz",
]

_EBAY_DOMAINS = {"ebay.com", "www.ebay.com", "ebay.com.au", "www.ebay.com.au"}

# Defense in depth (PR #5 review): the include_domains request filter above
# is enforced by the search provider, not by us -- it's not a guarantee.
# identify_marketplace()/is_individual_listing_url() in search/util.py still
# recognise eBay listing URLs as valid (that logic is shared with
# comparable_research.py, where eBay evidence IS wanted), so without this
# explicit check here, an eBay result that slipped past include_domains
# (provider quirk, redirect, or a future config override) would sail
# straight through as a "valid individual listing" and become a buyable
# opportunity -- exactly what discovery must never do.
_EBAY_MARKETPLACES = {"eBay", "eBay AU"}


def _process_query_results(
    query: str,
    domains: list[str],
    results: list,
    seen_canonical: set,
) -> tuple[dict, list]:
    """Classifies one query's raw results against the run's running
    canonical-URL dedup set (updated in place) and returns a per-query log
    entry plus the subset of results that were newly unique.

    Kept as a small pure-ish helper (only side effect is mutating the
    passed-in `seen_canonical` set) so query-level logging/rejection
    counting is unit-testable without exercising the whole discovery
    pipeline (product ID, valuation, etc).
    """
    unique_results = []
    valid_count = 0
    duplicate_count = 0
    not_listing_count = 0
    ebay_count = 0
    for r in results:
        key = canonicalize_url(r.url)
        if key in seen_canonical:
            duplicate_count += 1
            continue
        seen_canonical.add(key)

        if identify_marketplace(r.url) in _EBAY_MARKETPLACES:
            # Reject outright -- never added to unique_results, so it can
            # never reach `deduped`/`candidates` in run_discovery below,
            # regardless of what include_domains asked the provider for.
            ebay_count += 1
            continue

        unique_results.append(r)
        if is_individual_listing_url(r.url):
            valid_count += 1
        else:
            not_listing_count += 1

    entry = {
        "query": query,
        "domains": list(domains),
        "raw_results": len(results),
        "unique_results": len(unique_results),
        "valid_individual_listings": valid_count,
        "rejected_duplicate": duplicate_count,
        "rejected_not_individual_listing": not_listing_count,
        "rejected_ebay": ebay_count,
    }
    return entry, unique_results


_CANDIDATE_GROUP_ORDER = ["turners_general_goods", "turners_vehicles", "other"]


def _candidate_group(result) -> str:
    """Classifies a candidate for FAIR SLOT ALLOCATION only, not for
    verification -- listing_verification.py has its own, stricter URL
    matching for that. Turners General Goods and the four vehicle divisions
    are the only two individual-listing URL shapes turners.co.nz has (see
    scanner/scrapers/turners_catalog.py and turners_vehicles.py), so "on
    turners.co.nz, not under /General-Goods/" is a reliable proxy for
    "vehicle division listing" among is_individual_listing_url() survivors,
    without duplicating turners_vehicles.DIVISIONS' path table here.
    """
    if "turners.co.nz" not in result.url:
        return "other"
    if "/General-Goods/" in result.url:
        return "turners_general_goods"
    return "turners_vehicles"


def _acquisition_evidence_tier(result) -> int:
    """Lower = stronger evidence that `result.price` reflects something
    close to a realistic acquisition price, using only already-observed
    auction state from scanner/scrapers/turners_catalog.py /
    turners_vehicles.py (scanner/search/auction_search.py carries it
    through onto SearchResult) -- never an invented or estimated number.

    0: a real, fixed, immediately-payable price (buy_now).
    1: active bidding AND the seller's reserve is confirmed met -- current
       price is close to a real transaction price.
    2: active bidding, reserve state unknown/not yet met/no reserve field
       at all (every Turners Vehicle candidate is here -- that division's
       pages never expose reserve_status) -- still more informative than
       an untouched listing.
    3: no bids placed yet (`starting_bid`), or auction state is unknown
       entirely (non-Turners sources, where price_type is always None) --
       the weakest usable evidence, but not excluded outright.
    4: no price at all.
    """
    if result.price is None:
        return 4
    if result.buy_now_price is not None:
        return 0
    if result.price_type == "current_bid" and result.reserve_status == "Reserve Met":
        return 1
    if result.price_type == "current_bid":
        return 2
    return 3


def _select_research_candidates(candidates: list, max_research: int, prefer_below: float) -> list:
    """Replaces a single global cheapest-first sort+slice (pre Run #35 live
    validation, that logic just did `candidates.sort(key=lambda r: (r.price
    is None, r.price > prefer_below, r.price)); candidates[:max_research]`).

    That let a large pool of $1 starting-bid General Goods listings consume
    the entire max_research_items budget and permanently locked out
    Vehicles -- confirmed in Run #35 (131 raw General Goods vs 80 raw
    Vehicle candidates; General Goods, scraped first per config.json's
    turners_categories order, won every $1 tie via Python's stable sort,
    and all 5 research slots went to General Goods).

    Two independent fixes:

    1. Within each source group, order by (acquisition evidence tier,
       over-budget, price) -- see _acquisition_evidence_tier(). The
       existing `prefer_purchase_price_below` concept is retained exactly
       as before, just demoted beneath the new evidence tier so a
       real-bid/buy-now candidate no longer loses to a cheaper but
       unevidenced $1 starting bid.
    2. Across groups (Turners General Goods / Turners Vehicles / everything
       else -- Tavily-sourced TradeMe/Thorntons/Mainland/other Turners
       hits), allocate max_research_items by round robin: one slot per
       non-exhausted group per round. Mirrors the existing round-robin
       pattern already in this codebase (query_generator.py's
       _round_robin_fill(), used for Tavily query allocation), applied
       here to candidate selection instead.

    Deterministic and side-effect-free: same input always produces the
    same output, no randomness, no estimated/invented prices.
    """
    def sort_key(r):
        return (
            _acquisition_evidence_tier(r),
            r.price is not None and r.price > prefer_below,
            r.price if r.price is not None else float("inf"),
        )

    groups: dict = {name: [] for name in _CANDIDATE_GROUP_ORDER}
    for r in candidates:
        groups[_candidate_group(r)].append(r)
    for name in groups:
        groups[name].sort(key=sort_key)

    selected: list = []
    next_index = {name: 0 for name in _CANDIDATE_GROUP_ORDER}
    while len(selected) < max_research:
        made_progress = False
        for name in _CANDIDATE_GROUP_ORDER:
            if len(selected) >= max_research:
                break
            i = next_index[name]
            pool = groups[name]
            if i < len(pool):
                selected.append(pool[i])
                next_index[name] = i + 1
                made_progress = True
        if not made_progress:
            break  # every group exhausted before the budget was fully used
    return selected


def _build_unverified_watch_opportunity(candidate, verified) -> Opportunity:
    """Phase 4B.3: preserves a discovery candidate whose source
    listing_verification.verify_listing() reports as "unsupported" (e.g.
    Trade Me, Thorntons, Mainland Auctions -- a compliant re-fetch is
    structurally impossible for these, see that module's docstring) as a
    clearly labelled WATCH opportunity, instead of the previous behaviour
    of discarding it identically to a genuinely "unavailable" candidate.

    Deliberately does NOT call identify_product/research_comparables/
    apply_valuation/score_and_decide -- running the paid AI/valuation
    pipeline on a price that was never independently confirmed would
    present false precision on evidence Phase 4B.1 already established
    isn't trustworthy alone (Tavily search-snippet text), and burns AI
    budget on a candidate this function can already tell isn't going to
    reach BUY. Only what discovery itself already observed is carried
    through -- title/url/source/price/price_type/buy_now_price/
    reserve_status/closing_date/starts_on, exactly as scraped -- nothing
    here is invented, and every valuation/scoring field (flip_score,
    max_buy_price, expected profit/ROI, etc.) is left at its dataclass
    default (None/"unknown") rather than fabricated.

    decision is hardcoded "WATCH" and verification_status="unsupported"
    -- this candidate can never reach "BUY" or "PROFITABLE BUT CAPITAL
    RISK" through this path, by construction, not by downstream filtering.
    """
    reasons = [
        f"Verification unsupported: {verified.reason}",
        "Price and evidence are UNVERIFIED (from search-result text only, "
        "not re-fetched from the listing itself) -- open the listing and "
        "confirm price, condition, and availability manually before any "
        "purchase decision.",
    ]
    if candidate.description:
        reasons.append(f"Search snippet: {candidate.description}")
    if candidate.location:
        reasons.append(f"Location (from search result, unverified): {candidate.location}")

    return Opportunity(
        title=candidate.title,
        url=candidate.url,
        source=identify_marketplace(candidate.url),
        current_price=candidate.price,
        price_type=candidate.price_type,
        buy_now_price=candidate.buy_now_price,
        reserve_status=candidate.reserve_status,
        closing_date=candidate.closing_date,
        starts_on=candidate.starts_on,
        verification_status="unsupported",
        decision="WATCH",
        decision_reasons=reasons,
    )


def run_discovery(config: dict) -> list[Opportunity]:
    discovery_cfg = config.get("discovery", {})
    if not discovery_cfg.get("enabled", False):
        print("[discover] discovery.enabled is false in config.json -- skipping. "
              "Set it to true (and configure a web search provider) to run this mode.")
        return []

    # Tavily/web-search unavailability must only skip the Tavily-side path
    # below -- it must NOT exit run_discovery() early. AuctionSearchSource
    # (Turners direct-scrape discovery, see below) has its own working
    # scrapers and doesn't depend on a web search provider at all; the old
    # hard `return []` here predates AuctionSearchSource being wired into
    # this function and was only ever correct back when Tavily was the sole
    # candidate source discover.py had.
    web_search = WebSearchSource()
    if not web_search.available:
        print("[discover] No web search provider configured (set WEB_SEARCH_PROVIDER + "
              "its API key env var, e.g. WEB_SEARCH_PROVIDER=tavily + TAVILY_API_KEY). "
              "Tavily-based web search discovery will be skipped this run -- continuing "
              "with Turners direct-scrape discovery (AuctionSearchSource) only.")

    max_queries = discovery_cfg.get("max_queries_per_run", 15)
    max_results = discovery_cfg.get("max_results_per_query", 8)
    max_research = discovery_cfg.get("max_research_items", 5)
    prefer_below = discovery_cfg.get("prefer_purchase_price_below", 250)

    query_gen_cfg = config.get("query_generation", {})
    concepts = query_gen_cfg.get("concepts", [])
    bare_product_min_ratio = query_gen_cfg.get("bare_product_min_ratio", 0.15)
    products = discovery_cfg.get("products", [])

    # Rotates which products/concepts get priority in the round-robin below
    # (see allocate_discovery_queries docstring) so coverage cycles across
    # the full product/concept lists over successive days instead of always
    # favouring whatever's first in config.json. Config can pin a fixed
    # value (useful for debugging a specific day's behaviour); defaults to
    # today's date so it changes daily on its own.
    rotation_seed = discovery_cfg.get("rotation_seed")
    if rotation_seed is None:
        rotation_seed = date.today().toordinal()

    # Domain allowlist actually restricts Tavily's results server-side
    # (include_domains), replacing the old "site:trademe.co.nz" literal
    # query text, which is not a real filter for Tavily and let eBay/other
    # off-target domains flood the 15-query budget (Run #23). Config can
    # override the list, but eBay is stripped out unconditionally --
    # opportunity discovery must stay NZ-local, never eBay.
    discovery_domains = discovery_cfg.get("include_domains") or DEFAULT_DISCOVERY_DOMAINS
    discovery_domains = [d for d in discovery_domains if d.lower() not in _EBAY_DOMAINS]

    if web_search.available:
        queries = allocate_discovery_queries(
            products=products,
            concepts=concepts,
            max_queries=max_queries,
            bare_product_min_ratio=bare_product_min_ratio,
            seed=rotation_seed,
        )
        print(f"[discover] running {len(queries)} discovery quer{'y' if len(queries)==1 else 'ies'} "
              f"across {len(products)} product(s), restricted to domains: {', '.join(discovery_domains)}")
    else:
        # Nothing to allocate a Tavily query budget for -- Turners discovery
        # below doesn't use `queries` at all.
        queries = []

    stats = load_stats()
    discovered_store = load_discovered()
    all_results = []
    deduped = []
    seen_canonical: set = set()

    # Turners (General Goods + Vehicles) already has working scrapers that
    # reach real inventory directly, unlike Tavily web search, which rarely
    # surfaces individual Turners listings (see Runs #28-30). Processed FIRST
    # so its canonical URLs populate seen_canonical before the Tavily loop
    # below -- if the same listing also comes back from Tavily, the Turners
    # copy (already carrying a real scraped price) wins the duplicate, and
    # the Tavily copy is dropped as `rejected_duplicate`. Reuses the same
    # _process_query_results()/candidates/verification/valuation pipeline as
    # every other source -- no special-casing downstream of this point.
    auction_source = AuctionSearchSource(config)
    try:
        auction_results = auction_source.search()
    except Exception as e:
        # AuctionSearchSource already swallows its own scraper-level
        # failures (see scanner/search/auction_search.py) -- this is a
        # last-resort guard so an unexpected failure here can never take
        # down the Tavily loop below it in the same run.
        print(f"[discover]   auction source failed unexpectedly: {e}")
        auction_results = []
    for r in auction_results:
        r._discovery_concept = None  # not part of Tavily's concept-rotation stats
    all_results.extend(auction_results)
    auction_log_entry, auction_unique = _process_query_results(
        "auction_source:turners", ["turners.co.nz", "thorntons.net.nz", "mainlandauctions.nz"],
        auction_results, seen_canonical,
    )
    deduped.extend(auction_unique)
    print(
        f"[discover]   source=auction raw={auction_log_entry['raw_results']} "
        f"unique={auction_log_entry['unique_results']} "
        f"valid_listings={auction_log_entry['valid_individual_listings']} "
        f"rejected(duplicate={auction_log_entry['rejected_duplicate']}, "
        f"not_individual_listing={auction_log_entry['rejected_not_individual_listing']}, "
        f"ebay={auction_log_entry['rejected_ebay']})"
    )

    for query in queries:
        results = web_search.search(query, max_results=max_results, include_domains=discovery_domains)
        concept = extract_concept_from_query(query, concepts)
        # Record every result's discovery under this query's concept for
        # later query-strategy analysis, even before we know if it's profitable.
        for r in results:
            r._discovery_concept = concept  # lightweight tag, not part of SearchResult schema
        all_results.extend(results)

        log_entry, unique_results = _process_query_results(query, discovery_domains, results, seen_canonical)
        deduped.extend(unique_results)
        print(
            f"[discover]   query={log_entry['query']!r} "
            f"raw={log_entry['raw_results']} unique={log_entry['unique_results']} "
            f"valid_listings={log_entry['valid_individual_listings']} "
            f"rejected(duplicate={log_entry['rejected_duplicate']}, "
            f"not_individual_listing={log_entry['rejected_not_individual_listing']}, "
            f"ebay={log_entry['rejected_ebay']})"
        )

    # Search snippets rarely carry a structured price field -- best-effort
    # extract one from title/description text so bankroll-aware sorting
    # below has something to work with. Leaves price=None (never guesses)
    # if no price pattern is found in the text.
    for r in deduped:
        if r.price is None:
            r.price = extract_price(f"{r.title} {r.description}")

    new_urls = record_sightings(deduped, discovered_store)
    save_discovered(discovered_store)
    print(f"[discover] {len(all_results)} raw results -> {len(deduped)} unique listings "
          f"({len(new_urls)} newly seen).")

    # Only individual listing/lot pages on a recognised marketplace have a real
    # price to extract and value -- category pages, browse pages, YouTube videos,
    # Etsy category pages, retailer collection pages, etc. are excluded outright
    # (identify_marketplace() alone isn't enough here: it returns the bare hostname
    # for any unrecognised domain rather than "unknown", so a naive
    # "!= unknown" check let almost everything through).
    candidates = [r for r in deduped if is_individual_listing_url(r.url)]

    # See _select_research_candidates() docstring above for the full
    # rationale (Run #35 live validation finding: cheapest-first alone let
    # $1 General Goods starting bids consume the whole research budget).
    candidates = _select_research_candidates(candidates, max_research, prefer_below)
    candidates_found = len(candidates)

    # Phase 4B.1: a candidate's price (and everything downstream of it --
    # product ID, comparable research, valuation, Flip Score) must never be
    # trusted from Tavily's search-snippet text alone. Re-fetch each
    # candidate's actual authoritative source and drop anything that can't
    # be verified *before* any AI/research/valuation work runs on it -- see
    # scanner/listing_verification.py for what "verified" means per source.
    user_agent = config.get("user_agent", "NZ-Reseller-Scanner/1.0")
    request_delay = config.get("request_delay_seconds", 2.0)
    verification_cache = VerificationCache(user_agent, request_delay)

    verified_candidates = []
    watch_unverified_opportunities: list[Opportunity] = []
    verification_dropped = 0
    for candidate in candidates:
        verified = verify_listing(candidate.url, verification_cache)
        if verified.status == "verified":
            candidate.price = verified.price  # overwrite snippet-derived price with the authoritative one
            verified_candidates.append(candidate)
            continue
        if verified.status == "unsupported":
            # Phase 4B.3: structurally can't be compliantly re-verified
            # (Trade Me/Thorntons/Mainland Auctions) -- preserved as a
            # WATCH opportunity (see _build_unverified_watch_opportunity)
            # instead of being dropped like a genuinely "unavailable"
            # candidate below. Never joins `verified_candidates`, so it
            # can never reach identify_product/valuation/score_and_decide.
            watch_unverified_opportunities.append(
                _build_unverified_watch_opportunity(candidate, verified)
            )
            print(
                f"[discover]   verification unsupported -> WATCH (unverified): "
                f"url={candidate.url!r} reason={verified.reason!r}"
            )
            continue
        # status == "unavailable" (or anything else non-"verified"): the
        # source was attempted but no authoritative price/data could be
        # found (e.g. item not on page 1 of a Turners catalog) -- still
        # dropped outright, unchanged from pre-4B.3 behaviour.
        verification_dropped += 1
        print(
            f"[discover]   verification dropped: status={verified.status} "
            f"url={candidate.url!r} reason={verified.reason!r}"
        )

    print(
        f"[discover] verification: {len(verified_candidates)} verified, "
        f"{len(watch_unverified_opportunities)} unsupported (preserved as WATCH), "
        f"{verification_dropped} dropped (of {len(candidates)} candidates)."
    )
    candidates = verified_candidates

    api_key = config.get("anthropic_api_key", "")
    bankroll_cfg = config.get("bankroll", {})
    cost_model = config.get("cost_model", {})
    weights = config.get("flip_score_weights", {})
    risk_phrases = config.get("condition_risk_phrases", [])

    opportunities: list[Opportunity] = []
    for candidate in candidates:
        identification = identify_product(candidate.title, candidate.description, api_key)
        risk_level, matched = detect_condition_risk(
            f"{candidate.title} {candidate.description}", risk_phrases
        )
        identification.condition_risk_level = risk_level
        identification.condition_risk_phrases = matched

        evidence = research_comparables(
            candidate.title, web_search, max_results_per_query=max_results, exclude_url=candidate.url
        )

        researcher_result = research(candidate.title, candidate.price, evidence, api_key)
        valuation, trader_verdict = trader_review(
            title=candidate.title,
            price=candidate.price,
            researcher_result=researcher_result,
            evidence=evidence,
            costs_excl_purchase=0,  # refined by apply_valuation below once costs are known
            bankroll=bankroll_cfg.get("starting_bankroll", 500),
            api_key=api_key,
        )

        opportunity = Opportunity(
            title=candidate.title,
            url=candidate.url,
            source=identify_marketplace(candidate.url),
            current_price=candidate.price,
            # Carried through from the pre-verification candidate -- a
            # known, small limitation: if bidding activity happened in the
            # brief window between initial scrape and verify_listing()'s
            # re-fetch, this could be stale relative to the now-current
            # verified price. Not worth widening listing_verification.py's
            # scope to close (see scanner/listing_verification.py's own
            # docstring on what it does and doesn't verify).
            price_type=candidate.price_type,
            # Phase 4B.2 follow-up (persistence port): same carried-through-
            # from-pre-verification-candidate rationale as price_type above.
            buy_now_price=candidate.buy_now_price,
            reserve_status=candidate.reserve_status,
            closing_date=candidate.closing_date,
            starts_on=candidate.starts_on,
            identification=identification,
            valuation=valuation,
        )
        opportunity.liquidity, opportunity.expected_sale_time = estimate_liquidity(evidence)

        apply_valuation(opportunity, cost_model, bankroll_cfg)
        score_and_decide(opportunity, weights, bankroll_cfg)

        concept = getattr(candidate, "_discovery_concept", None)
        if concept:
            record_query_concept_result(stats, concept, opportunity.decision)

        opportunities.append(opportunity)

    save_stats(stats)

    # Phase 4B.3: append the preserved-but-unverified WATCH opportunities
    # after the scored loop above, not into `candidates`/the loop itself --
    # they were never meant to reach identify_product/valuation, and this
    # keeps that guarantee structural rather than relying on every field
    # on them happening to be falsy. flip_score is None for all of these,
    # so the sort below (None -> 0) places them alongside/after PASS-band
    # scored opportunities rather than displacing any real BUY/WATCH result.
    opportunities.extend(watch_unverified_opportunities)

    opportunities.sort(key=lambda o: o.flip_score or 0, reverse=True)

    # Phase 4B.2 (persistence port): persist every Opportunity from this run
    # (BUY, WATCH, PASS, and PROFITABLE BUT CAPITAL RISK alike) plus the run
    # metadata already computed above, so a durable, inspectable record
    # exists that downstream UI/reporting (see scanner/deal_queue_report.py)
    # can read without recomputing or inventing any valuation/scoring
    # logic. Written even when opportunities is empty, since the run itself
    # (queries/candidates/verification counts) is still worth recording for
    # debugging. Ported manually from commit f75a4eb onto the current
    # candidate-selection/evidence-tier pipeline -- see
    # scanner/discovery_report.py, which this does not modify.
    run_meta = {
        "run_timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "discover",
        "queries_run": len(queries),
        "candidates_found": candidates_found,
        "candidates_verified": len(verified_candidates),
        # Phase 4B.3: split out from candidates_verification_dropped --
        # these were preserved as WATCH opportunities (see
        # watch_unverified_opportunities above), not discarded. Only
        # genuinely "unavailable" candidates count as dropped now.
        "candidates_verification_unsupported": len(watch_unverified_opportunities),
        "candidates_verification_dropped": verification_dropped,
        "opportunity_count": len(opportunities),
        "decision_counts": dict(Counter(o.decision for o in opportunities)),
    }
    report_path, report_payload = write_discovery_report(opportunities, run_meta)
    update_discovery_index(report_path, report_payload)
    print(f"[discover] wrote {len(opportunities)} opportunit{'y' if len(opportunities) == 1 else 'ies'} to {report_path}")

    return opportunities


def print_top_opportunities(opportunities: list[Opportunity], limit: int = 10) -> None:
    print("\n\U0001F525 TOP FLIPS\n")
    for i, o in enumerate(opportunities[:limit], 1):
        val = o.valuation
        print(f"{i}. {o.title}")
        if o.current_price is not None:
            current_line = f"Current: ${o.current_price:.0f}"
            if o.price_type == "starting_bid":
                # Preserve the observed bid (still printed, unchanged) but
                # make it unmistakable that it is not a confirmed
                # acquisition price -- see valuation.py's
                # compute_profit_and_roi() for why expected profit/ROI
                # are absent below for exactly this case.
                current_line += " (starting bid, no bids yet -- not a confirmed price)"
            print(current_line)
        else:
            print("Current: unknown")
        if val.quick_sale_low is not None:
            print(f"Quick resale: ${val.quick_sale_low:.0f}-{val.quick_sale_high:.0f}")
        if o.expected_net_profit_low is not None:
            print(f"Expected profit: ${o.expected_net_profit_low:.0f}"
                  + (f"-{o.expected_net_profit_high:.0f}" if o.expected_net_profit_high else ""))
        if o.roi_low_pct is not None:
            print(f"ROI: {o.roi_low_pct:.0f}%" + (f"-{o.roi_high_pct:.0f}%" if o.roi_high_pct else ""))
        if o.price_type == "starting_bid" and o.expected_net_profit_low is None:
            print("Profit/ROI: not computed -- auction hasn't been bid on yet, so the "
                  "current price isn't a reliable cost basis. See Max buy for the "
                  "actionable ceiling.")
        if o.max_buy_price is not None:
            print(f"Max buy: ${o.max_buy_price:.0f}")
        print(f"Score: {o.flip_score}")
        print(f"Confidence: {val.confidence_pct:.0f}%")
        print(f"Decision: {o.decision}")
        print(f"Listing: {o.url}")
        print()


def send_discovery_alerts(opportunities: list[Opportunity], config: dict, min_score: int = 70) -> int:
    bot_token = config.get("telegram_bot_token", "")
    chat_id = config.get("telegram_chat_id", "")
    if not bot_token or not chat_id:
        return 0
    sent = 0
    for o in opportunities:
        if o.decision in ("BUY", "PROFITABLE BUT CAPITAL RISK") and (o.flip_score or 0) >= min_score:
            if send_telegram_message(bot_token, chat_id, build_flip_alert(o)):
                sent += 1
    return sent
