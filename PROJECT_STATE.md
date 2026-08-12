# Project State

_Last updated: 2026-08-12_

## Status

- `main` @ `4195ef7`. PRs #1-#10 merged, none open. 168/168 tests passing.
- **Phase 4A is validated end-to-end against live data.** GitHub Actions Run #25 on `main` succeeded with working Tavily auth: 15 queries across 12 products → 119 raw results → 105 unique (14 duplicates) → 84 rejected as non-individual-listing pages → 21 genuine individual listings passed URL validation → 5 reached product ID/research/valuation, all 5 correctly scored PASS. 0 eBay leakage throughout. Report auto-committed as `d7401ea`.
- PR #10 (`49708a7`) resolved the discovery query-allocation known issue: rebalanced `allocate_discovery_queries()` toward concept/bargain-signal queries (round 0 no longer 100% bare-product) and added daily product/concept rotation.

## Known issues

None currently open.

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

Phase 4A is validated and the query-allocation known issue is resolved. Next: decide whether to start Phase 4B or invest in the reporting/dashboard layer.
