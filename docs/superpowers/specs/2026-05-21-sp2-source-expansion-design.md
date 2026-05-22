# SP2 — Source Expansion (Design Spec)

**Date:** 2026-05-21
**Author:** Divyesh Sharma (with Claude)
**Status:** Design — implementation plan + code follow.
**Parent:** `docs/superpowers/specs/2026-05-10-phase3-saas-master-design.md` §SP2
**Roadmap entry:** `PHASE3_ROADMAP.md` §SP2

---

## 1. Scope of this SP — *narrower than the master spec*

The master spec for SP2 lists six deliverables: a `Source` protocol plus five new trend sources (Google Trends via pytrends, Meta Ad Library, TikTok Creative Center, AliExpress trending, Shopify-link scraper). Implementing all five at once concentrates legal, anti-bot, and maintenance risk into one PR.

**This SP implements:**

1. **`Source` protocol** at `el/sources/__init__.py`. Defines the typed contract every trend source must satisfy.
2. **YouTube source** — `el/sources/youtube.py`. Refactor of the existing `el/nodes/youtube_trending.py` to conform to the protocol. **Zero behavior change** — the existing node becomes a thin adapter.
3. **Shopify competitor source** — `el/sources/shopify_competitor.py`. Given a `*.myshopify.com` URL or any Shopify-powered store, fetch `/products.json` (a publicly documented Shopify endpoint, no scraping required) and emit candidates.
4. **Pipeline merge adapter** — small refactor of `el/pipeline.py` to load enabled sources from config and feed their combined output into the existing `score_rank` input shape via a new `ctx["source_candidates"]` list.

**Deferred to a future sub-project (call it "SP2-extra" when it lands):**

- **Google Trends via pytrends** — the existing `el/nodes/score_rank.py` already pulls Google Trends Daily RSS and Google News RSS. The marginal value of pytrends is "related queries" expansion, not new trend signal. Worth doing, but it's a content-improvement, not a source-shape change.
- **Meta Ad Library scraper** — public web access requires headless browsing through Browserbase. Meta's Terms of Service permit research access through the official Ad Library Report tool but explicitly disallow scraping. Skipping until we either (a) get explicit clearance, or (b) use the official API (Meta Ad Library API requires a Meta developer account + business verification — non-trivial onboarding).
- **TikTok Creative Center scraper** — same legal posture as Meta. ToS prohibit scraping. Defer pending clearance.
- **AliExpress trending** — public hot-products page but AliExpress aggressively blocks automated traffic. Requires Browserbase + residential proxy + ongoing maintenance for selector drift. Defer until the rest of the pipeline justifies the cost.

**Why this scope is right:** SP2 needs to ship the protocol so subsequent sources can be added incrementally without touching the pipeline core. The Shopify-link source proves the protocol works with a non-trivial new source that has zero legal risk. The four deferred sources can each become their own ~1-day sub-project once their preconditions are met, instead of bundled into one risky 7-day push.

---

## 2. The `Source` protocol

```python
# el/sources/__init__.py
from __future__ import annotations
from typing import Protocol, runtime_checkable
from dataclasses import dataclass


@dataclass(frozen=True)
class TrendCandidate:
    """A single trend signal — the unit every Source produces.

    `score_rank` consumes `TrendCandidate` lists via a thin adapter.
    """
    title: str                     # human-readable topic ("Wireless earbuds for kids")
    source_id: str                 # e.g. "youtube", "shopify_competitor:examplestore"
    raw_payload: dict              # arbitrary source-specific metadata
    score_hint: float | None = None  # optional pre-score from the source (e.g. view count)
    region: str = "IN"             # ISO country code; defaults to India for current scope
    fetched_at: str | None = None  # ISO-8601, set by run()


@runtime_checkable
class Source(Protocol):
    """Trend source contract.

    Every implementation must:
    - Be importable as a module with a top-level `SOURCE_ID` constant.
    - Expose `fetch_trends(ctx: dict) -> list[TrendCandidate]`.
    - Fail soft: on any error, return `[]` and log a warning. Pipeline never crashes.
    - Respect the source's published rate limits / robots.txt.
    """
    SOURCE_ID: str
    def fetch_trends(self, ctx: dict) -> list[TrendCandidate]: ...
```

**Why a Protocol, not an ABC:** sources are tiny, often single-file modules. Protocol gives us static typing without forcing inheritance boilerplate.

**Why `TrendCandidate` is frozen:** prevents downstream mutation that would invalidate the source's snapshot of what it fetched.

---

## 3. YouTube source — protocol-conforming wrapper

```
el/sources/youtube.py:
  SOURCE_ID = "youtube"
  def fetch_trends(ctx) -> list[TrendCandidate]:
      # delegates to el/nodes/youtube_trending.run() and wraps items as
      # TrendCandidate objects. No new API calls.
```

The existing `el/nodes/youtube_trending.py` keeps its current `run(ctx)` interface so the pipeline can keep calling it directly during transition. The new `el/sources/youtube.py` is an additional surface, not a replacement.

**Zero behavior change goal:** existing YouTube tests still pass without modification.

---

## 4. Shopify competitor source

```
el/sources/shopify_competitor.py:
  SOURCE_ID = "shopify_competitor"
  STORES_ENV_VAR = "EL_SHOPIFY_COMPETITOR_STORES"   # comma-separated list of store URLs
  def fetch_trends(ctx) -> list[TrendCandidate]:
      # for each configured store URL:
      #   GET <store>/products.json?limit=250&page=1..N
      #   emit one TrendCandidate per product (title=product.title,
      #     source_id="shopify_competitor:<store_handle>",
      #     score_hint=<product.published_at recency or vendor weight>,
      #     raw_payload=full product dict)
```

**Why `/products.json` is safe:** Shopify documents this endpoint as a public storefront API. It is returned by any standard Shopify store unless the merchant has explicitly disabled it. No scraping, no anti-bot evasion, no ToS gray area.

**Pagination:** Shopify caps the endpoint at 250 products per page. We page until either an empty page is returned or a configurable `EL_SHOPIFY_COMPETITOR_MAX_PAGES` (default 4 = 1000 products) is hit.

**Rate limiting:** Shopify storefront limits are generous (40 req/min per IP). With 4 pages per store and a small `EL_SHOPIFY_COMPETITOR_STORES` list, we stay well under.

**Failure modes (all fail-soft):**
- Store URL malformed → log warning, skip that store.
- HTTP non-200 (e.g., 404 — `/products.json` disabled) → log warning, skip that store.
- JSON malformed → log warning, skip that store.
- Network timeout → log warning, skip that store.

The source returns whatever it got from stores that succeeded.

---

## 5. Pipeline integration

`el/pipeline.py` currently has YouTube hardcoded:

```python
if config.get("YOUTUBE_API_KEY"):
    youtube_trending.run(ctx)
```

Refactor to a generic source-loop, while keeping the YouTube path identical for behavioral continuity:

```python
# Phase A (this SP):
sources = _load_enabled_sources()        # returns list[Source]
all_candidates: list[TrendCandidate] = []
for source in sources:
    all_candidates.extend(source.fetch_trends(ctx))
ctx["source_candidates"] = all_candidates

# YouTube remains for backwards compat — score_rank still reads ctx["youtube_items"].
# Future SPs collapse this once score_rank is refactored.
```

`_load_enabled_sources()` reads `EL_SOURCES_ENABLED` (default `"youtube"`) — a comma-separated list. Each name maps to its module. Unknown names log a warning and are skipped.

**Zero-behavior-change check:** with `EL_SOURCES_ENABLED` defaulting to `"youtube"`, the pipeline behaves identically to today. `score_rank` continues to read `ctx["youtube_items"]`. Adding `shopify_competitor` to the list extends the trend pool; score_rank ignores `ctx["source_candidates"]` unless we wire it in (deferred until a future SP that refactors score_rank's input shape).

So the safe staged rollout is: ship the protocol, the two sources, and `ctx["source_candidates"]`, but **don't yet feed `source_candidates` into score_rank**. That refactor is a separate concern with its own behavior risk.

---

## 6. Env vars added

| Var | Purpose | Default |
|---|---|---|
| `EL_SOURCES_ENABLED` | Comma-separated list of source module names to load | `"youtube"` |
| `EL_SHOPIFY_COMPETITOR_STORES` | Comma-separated list of Shopify store URLs (e.g. `https://examplestore.com,https://otherstore.myshopify.com`) | `""` (source becomes a no-op) |
| `EL_SHOPIFY_COMPETITOR_MAX_PAGES` | Pagination cap per store | `4` |

All three documented in `.env.example` with the same one-line-explanation style as SP1's env vars.

---

## 7. Tests

| File | What it covers |
|---|---|
| `tests/test_sources_protocol.py` | `TrendCandidate` immutability; `Source` Protocol runtime-check on the two real sources. |
| `tests/test_sources_youtube.py` | `youtube` source delegates to existing `youtube_trending.run()`; wraps items as `TrendCandidate` with correct `source_id` and `raw_payload`. |
| `tests/test_sources_shopify_competitor.py` | Pagination loop; fail-soft on HTTP 404, malformed JSON, timeout; per-store error isolation (one bad store doesn't kill others); empty `STORES` env → empty list. |
| `tests/test_pipeline_source_loop.py` | `_load_enabled_sources()` reads `EL_SOURCES_ENABLED`; unknown names skipped with warning; `ctx["source_candidates"]` populated; behavior identical when only YouTube is enabled (no `ctx["source_candidates"]` consumers exist yet). |

Project floor (90% line coverage) maintained.

---

## 8. Error handling & boundaries

Same fail-soft contract as existing nodes:
- Every source's `fetch_trends` is wrapped in try/except at the pipeline level. A crashing source logs the exception and contributes `[]` — the pipeline continues.
- Sources never raise their own exceptions across the protocol boundary — they catch and return `[]` internally.
- HTTP timeouts are bounded (default 30s, matching the existing `DEFAULT_TIMEOUT` in `youtube_trending.py`).

---

## 9. What this SP does NOT change

- `score_rank.py` — untouched. Its `ctx["youtube_items"]` input contract is preserved by the YouTube source delegating to the existing node.
- Any downstream node — untouched. The new `ctx["source_candidates"]` is additive and currently consumed by nothing.
- Database schema — none.
- External credentials — none new. Shopify storefront API is keyless.

---

## 10. Definition of done

Mirrors `PHASE3_ROADMAP.md` §Definition of Done. Specific to SP2:

1. Spec committed (this file) ✅.
2. Plan committed at `docs/superpowers/plans/2026-05-21-sp2-source-expansion.md`.
3. All plan tasks executed.
4. Full pytest suite green; overall `el/` coverage ≥ 90%.
5. New env vars documented in `.env.example`.
6. `docs/SP2_LOG.md` iteration log written.
7. PR merged to `main`.
8. `PHASE3_ROADMAP.md` status flipped to ✅; "Next action" advanced.

Post-merge production smoke (human, with creds):
- Add one real Shopify store URL to `EL_SHOPIFY_COMPETITOR_STORES`, add `shopify_competitor` to `EL_SOURCES_ENABLED`, run a batch, confirm `ctx["source_candidates"]` is populated (visible in pipeline-end log line) and no downstream node throws.

---

## 11. Risks specific to SP2

| Risk | Mitigation |
|---|---|
| Shopify endpoint disabled by some merchants → noisy 404 logs | Per-store fail-soft; downgrade to INFO (not WARNING) on first-time 404 to avoid alarm fatigue. |
| Adding sources without wiring `ctx["source_candidates"]` into `score_rank` means new sources don't influence rankings | Acceptable for now — documented in §5; follow-up SP refactors score_rank input shape. |
| `EL_SOURCES_ENABLED` typo silently disables a source | Pipeline logs WARN on unknown names. Optionally fail-loud (raise) if `EL_REQUIRE_ALL_SOURCES=true` is set — deferred unless requested. |
| Scope creep ("just add Meta Ad Library while you're here") | Explicit deferral in §1; revisit only after this SP merges. |
