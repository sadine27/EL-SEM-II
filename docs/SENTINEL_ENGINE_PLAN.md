# Sentinel Engine v1 Plan (revised + shipped)

Sentinel Engine is the vetting layer after Forge. Fenix answers *"what is
trending?"*, Forge answers *"where can we source it?"*, and **Sentinel answers
*"is this specific supplier product worth selling?"*** — scoring each Forge
candidate for quality, profitability, delivery, and IP risk.

> Status: implemented as a **preview / quality gate**. It reads
> `ctx["supplier_matches"]` and writes `ctx["sentinel_matches"]`. It does **not**
> replace the CJ / HIL / Phase 4 production path.

Default flow for v1:

```text
Fenix -> Forge -> Sentinel preview
```

The legacy daily HIL/Shopify flow is unchanged. (Forge itself is also still
preview-only — `supplier_search` is not wired into `pipeline.run()` — so Sentinel
sits on top of it with zero blast radius.)

## What changed from the original draft

This plan was revised after a code-grounded review. Five issues were fixed before
implementation:

1. **The margin gate was mathematically vacuous.** The original model set
   `sell = landed * MARKUP`, which makes
   `margin% = (sell − landed) / sell = 1 − 1/MARKUP` — a **constant** independent
   of the product. With `MARKUP=2.2` every item scored `0.545`, so
   `MIN_MARGIN_PCT=0.30` could never reject anything and the "rejects low margin"
   test was unconstructible. **Fix:** the sell price is now a **market reference
   price** when one is known (per-match `price_ceiling`/`market_price`/
   `suggested_retail`, the trend's `market_price`, or
   `EL_SENTINEL_DEFAULT_MARKET_PRICE`); only then does margin actually move. The
   `landed * MARKUP` value is kept as an informational fallback and tagged with a
   `margin_estimated_from_markup` warning so it is never a silent reject driver.
2. **`sentinel_score` / `EL_SENTINEL_MIN_SCORE` had no defined behaviour.** They
   are now a real soft-quality floor: a candidate that clears every hard gate but
   scores below `MIN_SCORE` is rejected with reason `low_sentinel_score`.
3. **Output shape was unspecified.** `sentinel_matches` now mirrors Forge's
   grouped `{trend, query, matches}` shape, so the CLI printer and any future
   consumer reuse the same iteration.
4. **Two config knobs were orphans.** `EL_SENTINEL_TOP_MATCHES_PER_TREND` (cap on
   surfaced passes) and `EL_SENTINEL_ENABLED` (no-op pass-through when `false`)
   now have defined behaviour.
5. **No env-parsing helpers exist in this repo** (`config.get` returns raw
   strings). The node carries its own `_bool_config` / `_float_config` /
   `_int_config`, matching the inline truthy idiom used elsewhere.

## Files

- `el/nodes/sentinel_vetting.py` — the gate. `run(ctx)` reads
  `ctx["supplier_matches"]`, writes `ctx["sentinel_matches"]`, never mutates the
  Forge originals.
- `el/pipeline.py` — `preview_sentinel(query=None, from_fenix=False, top=10,
  initial_ctx=None)` runs Forge then Sentinel. A shared `_forge_ctx` helper was
  extracted so `preview_forge` and `preview_sentinel` build matches identically.
- `el/__main__.py` — `sentinel` CLI subcommand (mirrors `forge`), with both a
  `--json` and a human-readable printer.
- `.env.example` — new "Sentinel Engine product vetting" section.
- `tests/test_sentinel_vetting.py` — node, preview, and CLI tests.

## CLI

```bash
python -m el sentinel --query "RCB jersey" --top 5 --json
python -m el sentinel --from-fenix --top 10 --json
python -m el sentinel --query "RCB jersey"          # human-readable
```

## Configuration (`.env`)

| Var | Default | Meaning |
| --- | --- | --- |
| `EL_SENTINEL_ENABLED` | `true` | `false` ⇒ no-op pass-through (`sentinel_decision="skipped"`). |
| `EL_SENTINEL_MIN_SCORE` | `0.62` | Soft floor; below ⇒ `low_sentinel_score` reject. |
| `EL_SENTINEL_TARGET_MARKUP` | `2.2` | Sell-price multiple **only** when no market price is known. |
| `EL_SENTINEL_MIN_MARGIN_PCT` | `0.30` | Hard reject below this projected margin. |
| `EL_SENTINEL_MAX_SHIPPING_DAYS` | `21` | Hard reject when supplier max ship days exceed this. |
| `EL_SENTINEL_TOP_MATCHES_PER_TREND` | `3` | Cap on surfaced **passing** matches per trend. |
| `EL_SENTINEL_BLOCK_IP_RISK` | `false` | `true` ⇒ IP-risk terms become hard rejects. |
| `EL_SENTINEL_DEFAULT_MARKET_PRICE` | `""` | Fallback market price so the margin gate bites for price-less sources. |

## Vetting behaviour

**Hard reject** (any one ⇒ `reject`):
- missing product title
- missing product URL
- stock explicitly `0`
- projected margin below `EL_SENTINEL_MIN_MARGIN_PCT` (only when a market price exists)
- shipping max days above `EL_SENTINEL_MAX_SHIPPING_DAYS`
- IP-risk terms **only** when `EL_SENTINEL_BLOCK_IP_RISK=true`
- `sentinel_score` below `EL_SENTINEL_MIN_SCORE` (when no hard reason already fired)

**Soft warning** (never flips the decision alone):
- missing image, unknown stock, unknown shipping, unknown rating, unknown cost
- `margin_estimated_from_markup` (no real market price available)
- IP-risk terms (`team`, `celebrity`, `movie`, `anime`, `game`, `character`) by default

> IP-risk defaults to **warn, not block** on purpose: the flagship niche is
> sports-team fan merch (`"RCB jersey"`), which would be wiped out by a default
> block.

**Margin model:** `landed_cost = cost + shipping_cost`;
`projected_margin_pct = (projected_sell_price − landed_cost) / projected_sell_price`.

**`sentinel_score`** blends (weights sum to 1.0): Forge relevance `0.30`, margin
health `0.25`, delivery `0.15`, stock `0.10`, rating `0.12`, image `0.08`, minus a
`0.10` IP-risk penalty.

Each vetted match carries the original Forge fields plus `sentinel_score`,
`sentinel_decision`, `sentinel_warnings`, `sentinel_rejection_reasons`,
`projected_sell_price`, `projected_margin_pct`. Each output group also includes a
`rejected` list (untruncated, for transparency) and a `summary` of counts.

## Test plan (implemented)

`tests/test_sentinel_vetting.py` covers: strong product passes; rejects on missing
title / missing URL / out-of-stock / low margin (against a market price) / slow
shipping; the **markup-only margin never rejects** regression; unknown
stock/shipping/rating warn but pass; IP-risk warns by default and blocks when
configured; `low_sentinel_score` reject path; `TOP_MATCHES_PER_TREND` truncation;
rejected-match transparency; `supplier_matches` immutability; disabled
pass-through; empty input safety; `preview_sentinel` query + from-fenix wiring;
and CLI JSON output.

```bash
pytest tests/test_sentinel_vetting.py tests/test_forge_preview.py
pytest
```

## Assumptions / scope

- No database migrations in v1.
- `phase4_candidate_selection` and the production HIL path are untouched.
- Sentinel v1 is a preview + Forge-quality gate, not the HIL replacement yet.
- Branch: this work shipped on the session branch `claude/ecstatic-bell-sR1im`
  (the draft named `codex/sentinel-product-vetting`; the session is pinned to the
  former).
