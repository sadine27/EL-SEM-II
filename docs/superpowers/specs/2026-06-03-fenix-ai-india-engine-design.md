# EL — AI India Trend Engine + Real Marketplace Listings (Design)

Date: 2026-06-03
Branch: `feat/fenix-ai-india-engine`
Status: Approved (brainstorming)

## Goal

Make EL run **real, end-to-end, on live Indian trends** with zero dummy/stub
data: AI discovers what is trending in India → real products are sourced from
Indian marketplaces with real images/prices → an aesthetic Shopify store is
built → Telegram HIL approval → Supabase persistence. The store is a
**demo/academic store: real-looking listings, no real order fulfillment**, which
lets us scrape marketplaces freely.

This replaces the brittle scraper roster (pytrends/reddit/amazon/newsapi) that
fails silently to zero, and the CJ supplier path that has no India-viral items.

## Why (diagnosis)

Live preview run on 2026-06-03 showed the true state:

- Working today (172 real topics): `rss_india` (41), `google_news_india` (51),
  `youtube` (50).
- Dead/blocked → return 0: `pytrends` (Google endpoint `404`),
  `reddit` (public JSON now blocked), `amazon_in_movers` (blocked).
  `newsapi` needs a key. Reddit/NewsAPI API keys require a multi-week approval
  the team cannot wait for.
- `cj_source` is real but is a **global generic catalog** — it never carries
  India-viral items (e.g. an "RCB IPL jersey"). `eprolo_source` is an
  acknowledged fake stub.

So the trend layer AND the supplier layer both need to change.

## Architecture

### 1. Fenix trend engine — AI + web search (primary), feeds as grounding

- New node/source `ai_trend_discovery`: a **Gemini agent (Vertex) with Tavily
  web search** that answers *"What products/topics are trending in India right
  now?"* and returns structured `TrendCandidate`s (title, why-trending,
  category from the existing 13-class taxonomy, source URL, score hint).
- The three working feeds (`rss_india`, `google_news_india`, `youtube`) are
  passed to the agent as **grounding context** so candidates are cross-checked
  against real headlines and each carries a citation URL (anti-hallucination).
- Removed from the active registry: `pytrends`, `amazon_in_movers`, `reddit`,
  `newsapi`. Code stays in the repo but is unregistered.
- Source hardening: every source logs an explicit `OK / EMPTY / BLOCKED` status
  so a silent-zero source can never again look like a total failure.

### 2. Product sourcing — real Indian marketplace listings (replaces CJ)

- New `marketplace_source`: per trend → AI builds a search query → **Tavily
  search → Browserbase fetch → Gemini extraction** → a real product from
  **Amazon.in / Flipkart / Meesho** with real title, image URL, price (₹),
  rating, and description, plus the source URL for provenance.
- `cj_source` and `eprolo_source` are dropped from the live supplier registry
  (retained inert in code).
- Normalizes into the existing review schema so downstream (HIL, Shopify,
  Supabase) is unchanged.

### 3. Aesthetic store

- Refresh `el/assets/theme_shells/` sections: cleaner hero, real product
  imagery from the scrape, ₹ pricing, India-oriented copy, improved
  typography/spacing.
- The Telegram approval card surfaces the polished product image.

### 4. Credentials & verification

- Required new env: `SHOPIFY_ADMIN_TOKEN` (custom-app Admin API token, scopes:
  `write_products`, `read_products`, `write_themes`, `read_themes`,
  `write_publications`) and `BROWSERBASE_PROJECT_ID`.
- Definition of done: a single `python -m el run` produces, all real and
  captured in the run log: AI-discovered India trends → marketplace products
  with images/prices → aesthetic Shopify store (live URL) → Telegram approval
  card → persisted Supabase rows. No stub/skip in the path.

## Out of scope

- Real order fulfillment / payments.
- Paper edits (the captured trace becomes real evidence later).
- Reviving pytrends / reddit / amazon / newsapi.

## Risks

- Marketplace anti-bot blocking → mitigated by Browserbase stealth + Tavily
  cache fallback + multiple marketplaces.
- AI trend hallucination → mitigated by feed grounding + required citation URL.
- Scraped image hotlinking on Shopify → may need to re-upload images to Shopify
  CDN during product create.
