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

- No database migrations.
- Sentinel is an **additive** review provider — it does not replace the CJ path.
- Branch: this work shipped on the session branch `claude/ecstatic-bell-sR1im`
  (the draft named `codex/sentinel-product-vetting`; the session is pinned to the
  former).

## Update: wired into the production daily run

Sentinel is no longer preview-only. The daily `pipeline.run()` now sources and
vets supplier products and feeds the **passing** picks into the human-in-the-loop
approval queue as an additional provider, alongside CJ. The legacy CJ path is
unchanged.

Flow added to `run()`:

```text
... -> ai_score_trends (Fenix)
     -> supplier_search (Forge)        # gated, fail-soft
     -> sentinel_vetting (Sentinel)    # gated, fail-soft
... -> normalize_cj_review
     -> normalize_sentinel_review      # passing picks -> hil_v1 rows
     -> merge_review_sources           # CJ + Browserbase + Sentinel
     -> phase4_candidate_selection -> HIL Telegram cards
```

Key pieces:

- **`el/nodes/normalize_sentinel_review.py`** — converts each passing Sentinel
  match into the `hil_v1` review contract, tagged `source_provider="forge_sentinel"`.
  `sentinel_score` (0..1) maps to `opportunity_score` on phase4's 0..10 scale
  (`× 10`), so a 0.62 vetting score clears phase4's `MIN_SCORE`.
- **`merge_review_sources`** now folds in `ctx["sentinel_review_items"]`.
- **`phase4_candidate_selection`** gains `SENTINEL_PROVIDER_CAP = 5` so the new
  provider is bounded (it shares the overall `TOTAL_CAP = 10`).
- **`EL_FORGE_PIPELINE_ENABLED`** (default `"true"`) is the master switch. Set it
  to `"false"` to make the daily run byte-for-byte identical to before. The whole
  stage is fail-soft: any crash is logged and the run continues on the CJ path.

Safety:

- The Forge/Sentinel sourcing runs after Fenix ranking but its HIL hand-off only
  takes effect where the CJ review branch runs (it merges right before
  `merge_review_sources`, inside the Google+CJ-credential block). On a system with
  CJ configured this means Sentinel picks reach the same Telegram cards; with no CJ
  branch the vetted matches are still computed into `ctx["sentinel_matches"]` but
  are not sent to HIL.
- Supplier sources fail soft to `[]` without their own credentials, so enabling the
  stage never crashes a credential-light run.

Tests: `tests/test_sentinel_hil_integration.py` covers the normalize contract
(field mapping, score scaling, dropping non-passing/incomplete rows), the merge
fold-in, an end-to-end check that a vetted row clears phase4's score gate and is
selected, the `forge_sentinel` provider cap, and the enablement switch.
