# Project State

_Last updated: 2026-08-11_

## Status

- `main` @ `20bb595`. PRs #1-#6 merged, none open. 163/163 tests passing.
- Phase 4A (discovery query-budget fix + NZ-local domain filtering, PR #5) is merged and structurally validated. It has **not** yet had a genuine live Tavily discovery run to confirm real-world behavior.

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

Run one genuine live Tavily discovery run to validate Phase 4A end-to-end before touching the query allocator or starting Phase 4B.