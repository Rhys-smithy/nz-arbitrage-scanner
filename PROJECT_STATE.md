# Project State

_Last updated: 2026-08-11_

## Current status

- `main` is at commit `942f67f` and unaffected by any work below.
- **PR #5** (draft, not merged): `phase-4a-discovery-query-fix` -> `main`.
  Fixes the Run #23 discovery bug (15-query budget exhausted on the first
  configured product; `site:` text wasn't a real Tavily filter). Adds
  `include_domains`-based NZ-local domain restriction, per-query logging,
  and tests. 160/160 tests passing at the point PR #5 was opened.
- Code review of PR #5 found one important gap: eBay exclusion in
  discovery had no defense-in-depth (relied solely on Tavily's
  `include_domains`, which is provider-enforced, not guaranteed). A fix is
  committed locally (`e3339cf`, 163/163 tests passing) but **not yet
  pushed** to GitHub -- pending push, PR #5 does not yet include it.
- Query-allocation strategy (round-robin across products) still weights
  bare-product queries over concept/bargain-signal queries within the
  budget -- flagged in review as a non-blocking future optimization.

## Environment constraint

This Claude sandbox clone has no GitHub push credentials and no GitHub
API access (`api.github.com` is network-blocked). Pushing requires: Claude
creates a `git bundle` file, the user downloads it and gets its real path
(Explorer "Show in folder" -> "Copy as path"), then runs
`git fetch <bundle> <branch>:<branch>` + `git push origin <branch>` from
their own machine, which already has push access. This applies to every
push/PR-update until a real credential path is set up.

## Next step

- Push commit `e3339cf` (eBay defense-in-depth fix) to update PR #5.
- Review/merge PR #5 once satisfied.
