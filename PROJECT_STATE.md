# Project State

_Last updated: 2026-08-12_

## Status

- `main` @ `e7d8770`. PRs #1-#8 merged, none open. 163/163 tests passing.
- **Phase 4A is validated end-to-end against live data.** GitHub Actions Run #25 on `main` succeeded with working Tavily auth: 15 queries across 12 products → 119 raw results → 105 unique (14 duplicates) → 84 rejected as non-individual-listing pages → 21 genuine individual listings passed URL validation → 5 reached product ID/research/valuation, all 5 correctly scored PASS. 0 eBay leakage throughout. Report auto-committed as `d7401ea`.

## Known issues

- Query-allocation (round-robin across products) over-weights bare-product queries vs. concept/bargain-signal queries within budget. Flagged in PR #5 review as non-blocking; not yet an approved change.

## Priorities

1. Find genuine NZ resale opportunities.
2. Improve valuation accuracy.
3. Improve comparable evidence.
4. Reduce false positives.
5. Improve search efficiency.
6. Protect the $500 bankroll.
7. Convenience/features last.

## Environment

Sandbox has no GitHub push credentials (`git push` fails, no username). No authenticated write path is currently active — see chat for options if this needs resolving.

## Next action

Phase 4A is validated — no further validation run needed. Next: decide whether to fix the query-allocation known issue, start Phase 4B, or invest in the reporting/dashboard layer.
