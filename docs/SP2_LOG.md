# SP2 — Source Expansion Iteration Log

**Spec:** `docs/superpowers/specs/2026-05-21-sp2-source-expansion-design.md`
**Plan:** `docs/superpowers/plans/2026-05-21-sp2-source-expansion.md`
**Started:** 2026-05-21
**Completed:** 2026-05-21

## Summary

SP2 introduces a `Source` protocol for trend discovery and ships two
implementations: a refactor of the existing YouTube Trending IN node as a
protocol-conforming source, and a new Shopify-competitor source that crawls
the publicly-documented `/products.json` endpoint of any Shopify-powered
store. The pipeline now loads enabled sources at the start of each batch
and aggregates their output into a new `ctx["source_candidates"]` field.

The master-spec list of five new sources was deliberately scoped down to
two — see the design spec §1 for the deferral reasoning (legal/ToS posture
for Meta Ad Library + TikTok, anti-bot maintenance cost for AliExpress,
marginal value over the existing RSS feed for pytrends Google Trends).

## What changed

| Area | Change |
|------|--------|
| New package | `el/sources/` — protocol + two source modules |
| Pipeline | `el/pipeline.py` loads enabled sources into `ctx["source_candidates"]` at run start; preserves backward-compat for the YouTube path |
| Config | New env vars: `EL_SOURCES_ENABLED`, `EL_SHOPIFY_COMPETITOR_STORES`, `EL_SHOPIFY_COMPETITOR_MAX_PAGES` |
| Tests | 30 new tests across protocol, YouTube source, Shopify source, and pipeline loop |
| Coverage | 463/463 tests green; overall `el/` coverage preserved above the 90% floor |

## Commits (in order)

| Commit | Task | What |
|---|---|---|
| `f1f27c4` | spec | Design spec |
| `28deb0a` | plan | Implementation plan |
| `28187ac` | Task 0 | `.env.example` docs for the three new env vars |
| `fb3f06e` | Task 1 | `Source` protocol + `TrendCandidate` dataclass |
| `fdd4d72` | Task 2 | `el/sources/youtube.py` (protocol wrapper) |
| `6071ea3` | Task 3 | `el/sources/shopify_competitor.py` (`/products.json`) |
| `37eb36f` | Task 4 | Pipeline source-loop |

## Deploy runbook

1. Pull the merged `main` into the deploy environment.
2. The default `EL_SOURCES_ENABLED="youtube"` makes SP2 behaviorally
   identical to pre-SP2 — no env-var edits required for a no-op deploy.
3. To enable the Shopify-competitor source: set
   `EL_SOURCES_ENABLED="youtube,shopify_competitor"` and populate
   `EL_SHOPIFY_COMPETITOR_STORES` with one or more Shopify store URLs
   (`https://examplestore.com,https://otherstore.myshopify.com`).
4. Run one production batch (`python -m el run`). Look for the line
   `EL pipeline: loaded N candidate(s) from M source(s)`. With YouTube
   only, N should match the YouTube fetch count. With Shopify enabled,
   N should be YouTube + (≤1000 × number of stores).
5. `ctx["source_candidates"]` is currently consumed by no downstream
   node — it is purely observational at this stage.

## Rollback

Remove `shopify_competitor` from `EL_SOURCES_ENABLED` (or set the var to
`"youtube"`) and redeploy/restart. Pipeline reverts to pre-SP2 source
behavior with one config change. No schema, no irreversible state.

## Acceptance verification

- [x] Source protocol defined and runtime-checkable.
- [x] YouTube source preserves existing `ctx["youtube_items"]` contract;
  no existing test required modification.
- [x] Shopify competitor source paginates, fails-soft per store, normalizes
  trailing-slash URLs, caps via env var.
- [x] Pipeline loads sources via env-var-driven registry; unknown names
  log a warning and are skipped.
- [x] 463/463 tests green; project coverage floor preserved.
- [ ] One end-to-end production batch with `shopify_competitor` enabled
  confirms `ctx["source_candidates"]` is populated. *(human verification
  post-merge.)*

## Surprises / decisions deferred

- **Did not feed `ctx["source_candidates"]` into `score_rank`.**
  `score_rank` has a complex input contract built around YouTube items
  and RSS feeds. Refactoring its input shape is its own concern with its
  own behavior risk; bundling it into SP2 would have expanded the blast
  radius. Deferred to a follow-up sub-project that owns the score_rank
  shape change.
- **YouTube backward-compat fallback.** The pipeline calls
  `youtube_trending.run()` directly only when YouTube is NOT in
  `EL_SOURCES_ENABLED` (so `score_rank` still gets its input). When
  YouTube is in the source list, the source itself calls
  `youtube_trending.run()` and populates `ctx["youtube_items"]` as a
  side-effect — same result, single call site. This dual path is the
  smallest seam consistent with zero behavior change.
- **Four sources deferred** (Google Trends pytrends, Meta Ad Library,
  TikTok Creative Center, AliExpress) — see design spec §1.
