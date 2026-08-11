# NZ Arbitrage Scanner — Claude Instructions

## Session Start

Read this file and `PROJECT_STATE.md` first. Inspect code only as needed for the task at hand. Don't reconstruct prior chat history from memory — Git history and these two files are the source of truth.

## Mission

Build a reliable NZ resale/arbitrage scanner: grow NZ$500 → NZ$10,000 by buying and reselling physical goods.

## Architecture

- Entry point: `main.py` (`--mode scan` default; `--mode discover` for Phase 3 web-search discovery).
- Core logic: `scanner/` (scrapers in `scanner/scrapers/`, search providers in `scanner/search/`).
- Tests: `tests/`.
- Full setup, config (`config.json`) reference, and pipeline/phase details: `README.md` — don't duplicate that here.
- Current state, known issues, priorities: `PROJECT_STATE.md`.

## Pipeline

SEARCH → LISTING VALIDATION → PRODUCT ID → COMPARABLE RESEARCH → VALUATION → COSTS → MAX BUY → PROFIT/ROI → RISK/LIQUIDITY → FLIP SCORE → BUY/WATCH/PASS

Keep opportunity sources separate from research/comparable sources.

## Rules

* Inspect existing code before changing it; reuse working code; make small, focused changes; don't touch unrelated functionality.
* Protect existing scanners, reports, Telegram, GitHub Actions, Phase 2 valuation, bankroll, and Flip Score.
* Never fabricate listings, prices, sold data, or comparable evidence. Clearly distinguish SOLD, ASKING, RETAIL, and OTHER evidence.
* AI researches/reasons; Python performs all financial calculations. Be conservative with valuations and confidence.
* Genuine individual listings only enter the opportunity pipeline — reject category/search pages, seller pages, YouTube, news, blogs, manufacturer pages, and generic retailer pages. Retail/product pages are fine as comparable/research evidence.
* Never bypass CAPTCHAs, authentication, bot protection, or marketplace access controls.
* Prefer free services; explain the free alternatives and cost/benefit before introducing a paid API.
* Filter cheaply before making expensive AI/research calls.
* Never commit or expose secrets. Mock external APIs in tests.
* Add a regression test for every bug fix; never weaken a test just to make it pass.
* Significant work goes on a separate branch with a focused commit. Never merge/push to `main` unless explicitly instructed.

## Decision Philosophy

Prefer fewer high-confidence opportunities over many weak ones (a likely $100 profit at high confidence beats a theoretical $250 at low confidence). Bankroll is $500, so capital concentration matters.

## Process

**Bug fix:** reproduce → find root cause → smallest fix → regression test → run targeted tests → full suite when appropriate.
**Feature:** check it doesn't already exist → find smallest integration point → consider API cost/failure modes → implement only what's required.

## Responses

Keep responses concise. Report only: changes made, tests passed, important limitations, decisions/input required. If blocked, state the exact blocker and the smallest decision needed.

---

Real-money decision-support system. When uncertain: be conservative, show the evidence, and say so.