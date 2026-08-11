# Project State

_Last updated: 2026-08-11_

## Current status

- `main` is at commit `942f67f` and unaffected by any work below.
- **PR #5** (draft, not merged): `phase-4a-discovery-query-fix` -> `main`.
  Fixes the Run #23 discovery bug (15-query budget exhausted on the first
  configured product; `site:` text wasn't a real Tavily filter). Adds
  `include_domains`-based NZ-local domain restriction, per-query logging,
  and tests. Contains commits `0180fe9` (the original fix) and `e3339cf`
  (eBay defense-in-depth, added after review). Both are pushed. 163/163
  tests passing.
- **PR #6** (draft, not merged): `docs/add-project-state` -> `main`. Adds
  this file. Documentation only.
- Query-allocation strategy (round-robin across products) still weights
  bare-product queries over concept/bargain-signal queries within the
  budget -- flagged in PR #5's review as a non-blocking future
  optimization.

## Environment constraint

This Claude sandbox clone has no GitHub push credentials and no GitHub
API access (`api.github.com` is network-blocked). Pushing requires: Claude
creates a `git bundle` file, the user downloads it and gets its real path
(Explorer "Show in folder" -> "Copy as path"), then runs
`git fetch <bundle> <branch>:<branch>` + `git push origin <branch>` from
their own machine, which already has push access. This applies to every
push/PR-update until a real credential path is set up.

## Next step

- Review/merge PR #5 and PR #6 once satisfied.
