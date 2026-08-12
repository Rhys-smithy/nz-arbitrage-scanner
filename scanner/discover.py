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

from datetime import date

from scanner.bundle import value_bundle
from scanner.comparable_research import extract_price, research_comparables
from scanner.discovery_store import load_discovered, record_sightings, save_discovered
from scanner.evidence import classify_evidence
from scanner.flip_score import score_and_decide
from scanner.liquidity import estimate_liquidity
from scanner.models import Opportunity, ProductIdentification
from scanner.notifier import build_flip_alert, send_telegram_message
from scanner.product_id import detect_condition_risk, identify_product
from scanner.query_generator import allocate_discovery_queries
from scanner.researcher import research
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
DEFAULT_DISCOVERY_DOMAINS = [
    "trademe.co.nz",
    "turners.co.nz",
    "thorntons.net.nz",
    "mainlandauctions.nz",
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


def run_discovery(config: dict) -> list[Opportunity]:
    discovery_cfg = config.get("discovery", {})
    if not discovery_cfg.get("enabled", False):
        print("[discover] discovery.enabled is false in config.json -- skipping. "
              "Set it to true (and configure a web search provider) to run this mode.")
        return []

    web_search = WebSearchSource()
    if not web_search.available:
        print("[discover] No web search provider configured (set WEB_SEARCH_PROVIDER + "
              "its API key env var, e.g. WEB_SEARCH_PROVIDER=tavily + TAVILY_API_KEY). "
              "Nothing to discover -- exiting rather than fabricating results.")
        return []

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

    queries = allocate_discovery_queries(
        products=products,
        concepts=concepts,
        max_queries=max_queries,
        bare_product_min_ratio=bare_product_min_ratio,
        seed=rotation_seed,
    )

    print(f"[discover] running {len(queries)} discovery quer{'y' if len(queries)==1 else 'ies'} "
          f"across {len(products)} product(s), restricted to domains: {', '.join(discovery_domains)}")

    stats = load_stats()
    discovered_store = load_discovered()
    all_results = []
    deduped = []
    seen_canonical: set = set()
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

    # Cheapest-first, capped to bankroll preference, then to max_research_items --
    # spec section 15: prioritise the $500 bankroll, avoid flooding with expensive items.
    candidates.sort(
        key=lambda r: (
            r.price is None,                          # priced items first
            r.price is not None and r.price > prefer_below,  # then within-budget items first
            r.price or float("inf"),                  # then cheapest first
        )
    )
    candidates = candidates[:max_research]

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

    opportunities.sort(key=lambda o: o.flip_score or 0, reverse=True)
    return opportunities


def print_top_opportunities(opportunities: list[Opportunity], limit: int = 10) -> None:
    print("\n\U0001F525 TOP FLIPS\n")
    for i, o in enumerate(opportunities[:limit], 1):
        val = o.valuation
        print(f"{i}. {o.title}")
        print(f"Current: ${o.current_price:.0f}" if o.current_price is not None else "Current: unknown")
        if val.quick_sale_low is not None:
            print(f"Quick resale: ${val.quick_sale_low:.0f}-{val.quick_sale_high:.0f}")
        if o.expected_net_profit_low is not None:
            print(f"Expected profit: ${o.expected_net_profit_low:.0f}"
                  + (f"-{o.expected_net_profit_high:.0f}" if o.expected_net_profit_high else ""))
        if o.roi_low_pct is not None:
            print(f"ROI: {o.roi_low_pct:.0f}%" + (f"-{o.roi_high_pct:.0f}%" if o.roi_high_pct else ""))
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
