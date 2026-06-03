# Pipeline believable-economics enrichment — design

**Date:** 2026-06-03
**Branch:** `feat/believable-economics`
**Goal:** Remove the "dummy" economics from the Fenix → Forge → Sentinel pipeline so the
demo store lists believable prices and the Sentinel gate does real, visible work.
**Non-goal:** Real dropship fulfillment / real wholesale sourcing. This is a
*believable demo store*: real product data, simulated-but-internally-consistent economics.

## Context: audit of what is real vs. dummy

- **Fenix (trend brain)** — REAL. `ai_trend_discovery` runs live Tavily + Gemini with a
  citation anti-hallucination contract; `score_rank` + `ai_score_trends` are real. No change.
- **Forge (`marketplace_source`)** — scrapes real Amazon.in/Flipkart listings (title, image,
  INR price, rating) via JSON-LD + LLM fallback. REAL data, but hollow economics:
  `shipping_cost = 0.0` hardcoded, `stock` binary, no shipping days.
- **Sentinel (`sentinel_vetting`)** — logic is sound but starved of inputs. The core flaw:
  the scraped **retail** price is stored as `cost`, then sold at `cost × 2.2` markup, so the
  margin gate is circular (admits it is "informational only") and **the store lists at 2.2×
  real retail** — the headline bug.
- **Stubs:** `eprolo_source.py` ("maps a fake-tested response shape") — off the default path
  but the only literal dummy. `curate_picks` per-run memory is a no-op (a feature gap, not a
  fake — out of scope).

## Decisions (confirmed with user)

1. **Believable demo store** — fix price inflation; economics may be simulated but must be
   internally consistent and believable.
2. **Simulate believable Sentinel economics** — list at real retail as the *sell* price;
   back-infer a plausible wholesale cost and shipping estimate so the margin/delivery gates
   compute real, believable values and visibly reject bad picks.

## Approach: simulate economics at the source, reuse Sentinel unchanged

Sentinel already does real margin math when given a market reference — it just never receives
one. Feeding it the right fields from Forge makes the gate come alive **with no Sentinel
changes**, honoring "make it better, not rebuild."

### Change 1 — `el/suppliers/marketplace_source.py`

Treat the scraped price as **retail** and derive a believable economic record on the
`SupplierCandidate`:

- `raw_payload["market_price"] = retail` → Sentinel's `_resolve_sell_price` uses the real
  scraped price as the sell price (basis `"market"`, not the circular markup).
- `cost = round(retail * EL_MARKETPLACE_COST_FACTOR, 2)`, default factor `0.55` → believable
  simulated wholesale cost. Margin becomes `(retail − landed) / retail ≈ 41%`, clearing the
  30 % floor honestly.
- `shipping_days_min / shipping_days_max` = simulated India estimate, default `3` / `7`
  (env `EL_MARKETPLACE_SHIP_DAYS_MIN` / `_MAX`) → Sentinel delivery score becomes real.
- `shipping_cost` = `0.0` (free-shipping marketplace norm; folded into landed via cost factor).
- `raw_payload["simulated_economics"] = True` for traceability/honesty.

`SupplierCandidate` has no `market_price` field, so the retail reference lives in
`raw_payload` — which `_resolve_sell_price` already inspects. No dataclass change.

### Change 2 — `sentinel_vetting.py`

**No logic change.** With `market_price` present, margin/delivery/stock signals stop hitting
their "unknown" defaults; the gate visibly rejects thin or over-priced picks.

### Change 3 — downstream price (fixed for free)

`normalize_sentinel_review` already uses `projected_sell_price` (now = real retail) as
`price_numeric`, so the Shopify listing lists at the **real scraped retail price** instead of
2.2× it. No change needed; covered by a regression test.

### Change 4 — delete the eprolo stub

Remove `el/suppliers/eprolo_source.py` and `tests/test_suppliers_eprolo.py`; drop `eprolo`
from `supplier_search.py`'s `_SUPPLIER_MODULES` / `_SOURCE_RELIABILITY`; clean
`.env.example` and `scripts/verify_env.py`. (`cj_source` stays — it is a real adapter, just
off the India default path.)

## Tests

- New marketplace economics test: a JSON-LD product with retail ₹1000 yields
  `cost ≈ 550`, `raw_payload["market_price"] == 1000`, shipping days `3–7`,
  `simulated_economics == True`.
- Sentinel regression: a marketplace-shaped match produces `projected_sell_price == retail`
  and `projected_margin_pct ≈ 0.45`, decision `pass`.
- `normalize_sentinel_review`: `price_numeric == retail` (not inflated).
- Full suite stays green.

## Out of scope

- Real wholesale sourcing / real fulfillment.
- `curate_picks` per-run memory (feature gap, emits no dummy output).
- `cj_source` (real adapter, off the India default path).
