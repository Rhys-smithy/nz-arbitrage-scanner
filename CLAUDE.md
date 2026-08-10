# NZ Arbitrage Scanner — Claude Instructions

## Mission

Build a reliable NZ resale/arbitrage scanner with the goal of growing NZ$500 → NZ$10,000 through buying and reselling physical goods.

## Rules

* Inspect existing code before changing it.
* Reuse working code; don't rebuild unnecessarily.
* Make small, focused changes.
* Don't modify unrelated functionality.
* Protect existing auction scanners, reports, Telegram, GitHub Actions, Phase 2 valuation, bankroll and Flip Score.
* Never fabricate listings, prices, sold data or comparable evidence.
* Clearly distinguish SOLD, ASKING, RETAIL and OTHER evidence.
* AI researches/reasons; Python performs all financial calculations.
* Be conservative with valuations and confidence.
* Genuine individual listings only may enter the opportunity pipeline.
* Reject category/search pages, seller pages, YouTube, news, blogs, manufacturer pages and generic retailer pages as opportunities.
* Retail/product pages may be used as comparable/research evidence.
* Never bypass CAPTCHAs, authentication, bot protection or marketplace access controls.
* Prefer free services. Do not introduce paid APIs without first explaining the free alternatives, cost and benefit.
* Avoid unnecessary API calls; filter cheaply before expensive AI/research calls.
* Never commit or expose secrets.
* Mock external APIs in tests.
* Add regression tests for bug fixes.
* Never weaken tests just to make them pass.
* For significant work, use a separate branch and focused commit. Do not merge/push to `main` unless explicitly instructed.

## Pipeline

SEARCH → LISTING VALIDATION → PRODUCT ID → COMPARABLE RESEARCH → VALUATION → COSTS → MAX BUY → PROFIT/ROI → RISK/LIQUIDITY → FLIP SCORE → BUY/WATCH/PASS

Keep opportunity sources separate from research/comparable sources.

## Decision Philosophy

Prefer fewer high-confidence opportunities over lots of weak ones.

A likely $100 profit with high confidence is better than a theoretical $250 profit with low confidence.

The starting bankroll is only $500, so capital concentration matters.

## Bug Fix Process

1. Reproduce.
2. Find root cause.
3. Make the smallest appropriate fix.
4. Add a regression test.
5. Run targeted tests.
6. Run the full suite when appropriate.

## Feature Process

Before coding:

* Check whether it already exists.
* Identify the smallest integration point.
* Consider API cost and failure modes.
* Implement only what is required.

## Responses

Keep responses concise.

After work, report only:

* changes made
* tests passed
* important limitations
* decisions/input required

If blocked, state the exact blocker and the smallest required decision.

## Current Priority

1. Find genuine NZ resale opportunities.
2. Improve valuation accuracy.
3. Improve comparable evidence.
4. Reduce false positives.
5. Improve search efficiency.
6. Protect the $500 bankroll.
7. Add convenience/features last.

This is a real-money decision-support system. When uncertain: be conservative, show the evidence, and say so.
