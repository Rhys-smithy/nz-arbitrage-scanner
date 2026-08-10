"""Phase 2 demo entry point -- NOT wired into the daily scan.yml pipeline.

Runs the new AI Flip Hunter engine end-to-end against a hand-built mock
listing (no live scraping, no AI calls, no Telegram) so the whole chain
-- product identification -> comparable evidence -> valuation -> cost
engine -> max buy price -> flip score -> decision -> alert text -- can be
inspected and sanity-checked before anything touches real money or the
existing daily automation.

Usage: python3 demo_flip_hunter.py
"""
import json

from scanner.bundle import value_bundle
from scanner.comparables import build_valuation_from_evidence
from scanner.flip_score import score_and_decide
from scanner.liquidity import estimate_liquidity
from scanner.models import ComparableEvidence, Opportunity, ProductIdentification
from scanner.notifier import build_flip_alert
from scanner.product_id import detect_condition_risk
from scanner.valuation import apply_valuation

with open("config.json") as f:
    CONFIG = json.load(f)


def run_demo():
    # Mock listing, matching the spec's own worked example (section 35).
    listing_title = "Old Nikon camera with lenses"
    listing_price = 205.0
    listing_text = "Nikon D90 with 18-105mm and 70-300mm lenses, battery, charger, bag. Works fine."

    # Product identification would normally call scanner.product_id.identify_product()
    # with an Anthropic API key. Hard-coded here since this demo runs with no key.
    identification = ProductIdentification(
        brand="Nikon", model="D90", is_bundle=True,
        model_identified_confidently=True,
    )
    risk_level, matched = detect_condition_risk(listing_text, CONFIG["condition_risk_phrases"])
    identification.condition_risk_level = risk_level
    identification.condition_risk_phrases = matched

    # Mock comparable evidence (in production: scanner.search + AI research pass)
    evidence = [
        ComparableEvidence("Nikon D90 bundle", "D90", "used", 330, "NZD", "TradeMe", "https://trademe.co.nz/x1",
                            "2026-08-05", 0.95, True),
        ComparableEvidence("Nikon D90 bundle", "D90", "used", 350, "NZD", "TradeMe", "https://trademe.co.nz/x2",
                            "2026-08-03", 0.9, True),
        ComparableEvidence("Nikon D90 body only", "D90", "used", 210, "NZD", "eBay AU", "https://ebay.com.au/x3",
                            "2026-07-20", 0.6, True),
    ]

    opportunity = Opportunity(
        title=listing_title,
        url="https://turners.co.nz/example-listing",
        source="Turners",
        current_price=listing_price,
        identification=identification,
    )
    opportunity.valuation = build_valuation_from_evidence(evidence, identification.model_identified_confidently)
    opportunity.liquidity, opportunity.expected_sale_time = estimate_liquidity(evidence)

    apply_valuation(opportunity, CONFIG["cost_model"], CONFIG["bankroll"])
    score_and_decide(opportunity, CONFIG["flip_score_weights"], CONFIG["bankroll"])

    print(build_flip_alert(opportunity))
    print()
    print("Bundle component check (illustrative, not this listing's real components):")
    bundle_val = value_bundle([100, 150, 90, 30])
    print(bundle_val)


if __name__ == "__main__":
    run_demo()
