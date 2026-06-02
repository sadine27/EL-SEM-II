# Fenix Engine — Detailed Changelog

This document records, in detail, the two commits that built the **Fenix engine**
(the trend data-collection + scoring front-end of the pipeline). Read it
top-to-bottom to understand what exists today and how it got here.

| Commit | Author | Date (local) | Summary |
|---|---|---|---|
| [`f4f3a25`](#1-f4f3a25--rebuild-data-collection--scoring-from-scratch) | Divyesh | 2026-06-02 12:32 IST | Rebuilt data collection & scoring from scratch |
| [`eaaa4f0`](#2-eaaa4f0--ai-trend-scoring--new-source--stabilize-regressions) | Claude (this session) | 2026-06-02 13:26 IST | AI trend scoring + new source + stabilize regressions |

---

## 1. `f4f3a25` — Rebuild data collection & scoring from scratch

**Author:** Divyesh `<sharmadivyesh20070727@gmail.com>` · **+988 / −110 across 9 files**

This was a ground-up rewrite of how the pipeline discovers and scores trends.

### What it changed

**Scoring rewrite — `el/nodes/score_rank.py` (+545 lines)**
- **Category-mapping bug fix.** Naive regex matching used to map "earbuds" →
  `fashion`. Replaced with **anchor-priority scoring**: high-specificity "anchor"
  terms score `+4 + 1.5 × word_count`, ordinary keywords score `+1`, with a
  per-category `priority` tie-breaker.
- **`TOPIC_EXCLUSIONS` hard-exclusion zones.** If a trigger term (e.g. "earbuds")
  appears, listed categories (fashion/home/beauty/…) are removed from
  consideration entirely — this is what actually fixes the earbuds bug.
- **Velocity detection** baked into `score_intent`: a rising trend earns up to
  `+0.35`, a falling one down to `−0.15`.
- **Cross-source confirmation boost**: each additional independent source that
  reports the same (normalized) topic adds `+0.08`, capped at `+0.30`.
- **Dedupe** by word-overlap (>0.70), keeping the higher-scored entry.
- **New sort key**: intent score → velocity → cross-source count.

**Five new sources — `el/sources/*` (all fail-soft)**
| File | Source | Key needed? | Velocity signal |
|---|---|---|---|
| `pytrends_source.py` | Google Trends IN (daily + realtime) | No | 7-day hourly window (recent avg vs baseline) |
| `reddit_source.py` | 14 India subreddits, hot posts | originally `REDDIT_CLIENT_ID/SECRET`; now public JSON scrape | log-normalised score/hour |
| `newsapi_source.py` | India commerce headlines | `NEWSAPI_KEY` | none |
| `amazon_in_source.py` | Amazon IN Movers & Shakers (scrape) | No | static `0.65` (definitionally rising) |
| `rss_india_source.py` | 10 Indian tech/commerce RSS feeds | No | none |

**Protocol — `el/sources/__init__.py`**
- `TrendCandidate` gained `velocity`, `search_volume`, `cross_source_count` fields.

**Wiring — `el/pipeline.py`**
- Registered the 5 new sources; changed the default (when `EL_SOURCES_ENABLED`
  is unset) from `["youtube"]` to a 6-source list.

**Dependencies — `requirements.txt`**
- Added `pytrends`, `praw`, `newsapi-python`, `beautifulsoup4`, `lxml`.
  `praw` was later removed when the Reddit source was converted to a no-key
  public JSON scraper.

### What it left broken (the gaps this session fixed)
- **No tests** for any of the 5 new sources or the new scoring logic.
- **5 existing tests silently broke** (see commit #2 below).
- **Undocumented config** — new env vars never added to `.env.example`, and
  `EL_SOURCES_ENABLED="youtube"` there contradicted the new code default.
- **Brittleness** — scoring is keyword-bound, so a brand-new viral product
  (e.g. "Labubu") that matches no keyword scores ~0 and lands in `uncategorized`.

---

## 2. `eaaa4f0` — AI trend scoring + new source + stabilize regressions

**Author:** Claude (this session) · **+1415 / −14 across 20 files**

Goal: make the engine **stop relying on keywords**, enable **all free sources**,
catch **event-driven fan merch** (e.g. "RCB jersey" after an IPL win), add the
missing tests/docs, and repair the regressions `f4f3a25` left behind.

### 2.1 New architecture — eyes → brain → safety-net

1. **Eyes (sources)** surface raw trending topics with no vocabulary limit.
2. **Brain (AI)** judges each raw topic with an open vocabulary.
3. **Safety-net (keywords)** remains as the fail-soft fallback.

### 2.2 Features added

**AI trend scoring — `el/nodes/ai_score_trends.py` (NEW, 188 lines)**
- Runs after `score_rank`. Sends the deduped topics to Gemini (reusing the
  existing `el/llm.py` Vertex layer) and, per topic, asks:
  `{is_product, intent 0..1, category, canonical_product}` — framed for the
  Indian market **including current-event fan merch**.
- AI `intent`/`category` **override** the keyword results, then the list is
  **re-ranked**.
- **Cost controls:** batched (`EL_AI_SCORING_BATCH`, default 40) and capped
  (`EL_AI_SCORING_MAX_TOPICS`, default 120).
- **Fail-soft everywhere:** disabled flag, missing `GOOGLE_SERVICE_ACCOUNT_JSON`,
  provider construction error, per-batch call error, or unparseable JSON all
  leave the affected topics on their keyword scores. `provider=` is injectable
  for tests.
- **Gated by:** `EL_AI_SCORING_ENABLED` (default `true`) + presence of Vertex
  service-account JSON.

**New no-key source — `el/sources/google_news_india_source.py` (NEW, 85 lines)**
- Topic-segmented Google News IN RSS across 6 commerce angles (trending, gadgets,
  deals, viral, sports merch, entertainment), scoped to the last 2 days. No key.

**Merch category — `el/nodes/score_rank.py` (+26 lines)**
- New `sports_and_merch` category (priority 9) with anchors/keywords like
  `jersey`, `rcb jersey`, `fan merch`, `merchandise`, `memorabilia`, `cap`,
  `flag`, plus exclusion zones so merch topics don't smear into
  electronics/grocery. "RCB jersey" now categorizes correctly even without AI.

**All-free default — `el/pipeline.py` (+42 lines)**
- Added `_DEFAULT_SOURCES` constant: `youtube, pytrends, reddit, newsapi,
  amazon_in_movers, rss_india, google_news_india`. Unset/empty
  `EL_SOURCES_ENABLED` now enables **all** of them; key-gated sources fail soft.
- Added `collect_and_rank()` helper: runs only fetch → score → AI → rank
  (no downstream nodes), so the front-end works with zero credentials.
- Wired `ai_score_trends.run` in immediately after `score_rank.run`.

**Preview CLI — `el/__main__.py` (+35 lines)**
- New subcommand `python -m el trends [--top N] [--json]` prints the ranked
  trends (AI-scored when creds exist, keyword fallback otherwise). Used to eyeball
  engine output offline.

### 2.3 Regressions fixed (all introduced by `f4f3a25`)
- **`tests/test_pipeline_source_loop.py`** — default-source assertions updated to
  expect `_DEFAULT_SOURCES`; added a test pinning the list and one verifying every
  default name resolves in the registry.
- **`el/nodes/score_rank.py` `dedupe`** — restored the "keep the entry with richer
  related_queries" tiebreak (dropped by the rewrite), as a final tuple element.
- **`tests/test_hardening_edges.py`** — `parse_youtube` now emits
  `velocity`/`search_volume`; expectation updated.
- **`tests/test_integration_pipeline.py`** — `fetch_trends`/`fetch_news` were
  renamed to `fetch_trends_rss`/`fetch_news_rss`; monkeypatch targets updated.

### 2.4 Real bugs found *by the new tests* and fixed in source
- **`el/sources/pytrends_source.py`** — `fetch_trends` raised `UnboundLocalError`
  in its final log line when `_make_client()` failed. `daily_titles` /
  `realtime_titles` are now hoisted before the `try`, restoring the fail-soft
  contract (returns `[]`).
- **`el/nodes/ai_score_trends.py`** — the system prompt contains literal JSON
  braces, which broke `str.format`; switched the category-list token to
  `str.replace`.

### 2.5 Unrelated pre-existing bug fixed
- **`el/nodes/upload_shopify_products.py` `_picks`** — now falls back to
  `curated_picks` when no HIL review rows exist, matching the documented test
  intent (`test_falls_back_to_curated_picks`). This was failing independently of
  the engine.

### 2.6 Tests added (fail-soft at every IO boundary)
| File | Covers |
|---|---|
| `tests/test_ai_score_trends.py` | AI override, re-rank, batching/cap, all fail-soft paths |
| `tests/test_sources_pytrends.py` | daily/realtime, velocity batch branches, ImportError, fail-soft |
| `tests/test_sources_reddit.py` | no-creds skip, velocity, MIN_SCORE filter, per-sub isolation |
| `tests/test_sources_newsapi.py` | no-key skip, 429 break, dedupe, `[Removed]`, fail-soft |
| `tests/test_sources_amazon_in.py` | selector fallback, ImportError, non-200, fail-soft |
| `tests/test_sources_rss_india.py` | title parse, dedupe, non-200, fail-soft |
| `tests/test_sources_google_news_india.py` | topic-segmented source_id, dedupe, fail-soft |
| `tests/test_score_rank.py` (extended) | velocity, cross-source, exclusions, merch, pluggable path |

**Coverage:** new modules ≥90% line coverage (95% aggregate).
**Full suite:** 738 passed, 1 skipped (opt-in compose smoke).

### 2.7 Documentation
- **`.env.example`** — documented `NEWSAPI_KEY`, the `EL_AI_SCORING_*` block,
  and the all-free `EL_SOURCES_ENABLED` default + every valid source name.
  Reddit no longer needs `REDDIT_*` credentials.
- **`docs/FENIX_LOG.md`** — eyes/brain/safety-net architecture + iteration log.

### 2.8 Verified offline
`python -m el trends --top 10` ran end-to-end with no credentials: the new
`google_news_india` source returned 58 live candidates, "Avengers: Doomsday
Merch" mapped to `sports_and_merch`, and the AI node cleanly no-opped to keyword
scoring (banner: "keyword-scored (no Vertex creds / AI off)").

---

## 3. Still pending (blocked on credentials — not code)

| Item | Unblocks when |
|---|---|
| Live Vertex smoke of the AI brain (confirm parseable JSON + token spend) | `GOOGLE_SERVICE_ACCOUNT_JSON` set |
| NewsAPI live fetches | `NEWSAPI_KEY` set |
| Optional grounded "what's trending in India" AI web-search source | `TAVILY_API_KEY` set |
| Install optional source libs in this environment | `pip install pytrends beautifulsoup4 lxml` |

All code paths above are already unit-tested against fakes; only live smoke runs
are deferred.
