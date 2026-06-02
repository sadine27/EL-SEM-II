# Fenix Engine — Iteration Log

The "Fenix engine" is the trend **data-collection + scoring** front-end of the
pipeline: it gathers raw trending topics from many sources, judges which are
buyable products and how hot they are, and emits a ranked payload that the rest
of the pipeline turns into a stocked store.

## Architecture: eyes → brain → safety-net

1. **Sources (eyes)** — `el/sources/*`, loaded by `el/pipeline.py`. Each emits
   `TrendCandidate` objects with no vocabulary limit, so they surface *whatever*
   is trending right now (a new toy like "Labubu", a "RCB jersey" spike after an
   IPL win, etc.). Shipped sources: `youtube`, `pytrends`, `reddit`, `newsapi`,
   `amazon_in_movers`, `rss_india`, `google_news_india`, plus `shopify_competitor`.
   Key-gated sources fail soft to `[]` when their credentials are absent.
2. **AI brain** — `el/nodes/ai_score_trends.py`. After the keyword scorer ranks
   topics, Gemini (via the existing `el/llm.py` Vertex layer) re-scores and
   re-categorizes each topic with an **open vocabulary**: *is this a physical
   product Indians would buy online now (incl. current-event fan merch)? how
   strong is buy-intent? what category?* This is what catches brand-new viral
   products that match no keyword. Fail-soft and cost-bounded (batched + capped).
3. **Keyword safety-net** — `el/nodes/score_rank.py`. Tiered buyer-intent
   keywords, velocity boost, cross-source confirmation boost, and anchor-priority
   category mapping with hard-exclusion zones. Always runs; remains the score of
   record when no Vertex credentials are available or the AI call fails.

## What shipped this pass

- **AI scoring node** (`ai_score_trends`) wired into `pipeline.run` right after
  `score_rank`. Gated by `EL_AI_SCORING_ENABLED` + `GOOGLE_SERVICE_ACCOUNT_JSON`;
  batched (`EL_AI_SCORING_BATCH`) and capped (`EL_AI_SCORING_MAX_TOPICS`).
- **New no-key source** `google_news_india` — topic-segmented Google News RSS
  (deals, gadgets, launches, sports merch, entertainment).
- **Reddit source no longer needs API credentials** — it now scrapes public
  subreddit JSON listing pages and fail-softs when Reddit blocks or changes a
  response.
- **`sports_and_merch` category** + merch exclusion zones in `score_rank`, so
  even without AI a "RCB jersey" topic categorizes correctly instead of falling
  into `uncategorized`.
- **All-free default**: an unset/empty `EL_SOURCES_ENABLED` now enables every
  shipped source (`pipeline._DEFAULT_SOURCES`) so nothing trending is missed.
- **Preview CLI**: `python -m el trends [--top N] [--json]` runs only
  fetch → score → AI → rank and prints the result — usable with no downstream
  credentials.
- **Test coverage** for all 5 prior Fenix sources + the new one + the AI node +
  the new score_rank logic. New modules ≥90% line coverage.

## Regressions fixed (introduced by the original Fenix rebuild `f4f3a25`)

The "from scratch" rebuild had landed without updating callers/tests:

- `pipeline._load_enabled_sources` default changed but `test_pipeline_source_loop`
  still asserted the old `["youtube"]` — updated to assert `_DEFAULT_SOURCES`.
- `score_rank.dedupe` dropped the "keep the entry with richer related queries"
  tiebreak — restored as a final tiebreaker.
- `score_rank.parse_youtube` gained `velocity`/`search_volume` keys —
  `test_hardening_edges` expectation updated.
- `fetch_trends`/`fetch_news` were renamed to `fetch_trends_rss`/`fetch_news_rss`
  — `test_integration_pipeline` monkeypatch targets updated.

Two real fail-soft bugs were found *by the new tests* and fixed in the source:

- `pytrends_source.fetch_trends` raised `UnboundLocalError` in its final log line
  when `_make_client()` failed — `daily_titles`/`realtime_titles` are now hoisted.
- `ai_score_trends` system prompt contained literal JSON braces; switched from
  `str.format` to `str.replace` for the category-list token.

Also fixed an unrelated pre-existing failure surfaced by the full run:
`upload_shopify_products._picks` now falls back to `curated_picks` when no HIL
rows exist (matches the documented test intent).

## Credential-gated TODOs (deferred — no creds in this environment)

- **Live Vertex smoke** of `ai_score_trends` once `GOOGLE_SERVICE_ACCOUNT_JSON`
  is provided: confirm the model returns parseable JSON and watch token spend.
- **NewsAPI live runs** once `NEWSAPI_KEY` is set.
- **Optional grounded AI source**: a web-search-backed "what's trending in India"
  source (needs `TAVILY_API_KEY`) to complement the source-fed AI brain.
