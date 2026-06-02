# SP5b — Shopify Auto-Store

**Date:** 2026-05-22
**Status:** Design
**Depends on:** SP5a (notify_business shipped)
**Blocks:** SP6 (CRM minimal)

## 1. Purpose

After HIL approves products, automatically:

1. Generate a small, deterministic theme spec (name, palette, fonts, hero/CTA copy) via Vertex Gemini.
2. Push that theme onto a configured Shopify dev store (theme settings + a single "story" snippet).
3. Push each approved product (title, body HTML, price, image URL, tags) as a Shopify product via Admin REST API 2024-10.
4. Append the resulting storefront URL into the existing `notify_business` Telegram ping.

All four nodes are **fail-soft**: any failure writes `formatted_error` and does not crash the pipeline. The whole sprint is gated by `SHOPIFY_STORE_DOMAIN + SHOPIFY_ADMIN_API_TOKEN`; when absent, the nodes are skipped entirely.

## 2. Architecture

```
HIL approve
   │
   ▼
generate_shopify_theme (Vertex Gemini, JSON-mode)
   │   ctx["shopify_theme"] = {name, palette{primary,secondary,accent,bg,text},
   │                            fonts{heading,body}, hero{headline,subhead,cta},
   │                            story_html}
   ▼
upload_shopify_theme (ShopifyAdminProvider.update_main_theme_settings)
   │   ctx["shopify_theme_result"] = {ok, theme_id, asset_keys}
   ▼
upload_shopify_products  (ShopifyAdminProvider.create_product, one per pick)
   │   ctx["shopify_product_results"] = [{ok, product_id?, handle?, error?}, ...]
   │   ctx["shopify_store_url"] = f"https://{domain}"
   ▼
notify_business  (now appends "Store: <url>" when shopify_store_url present)
```

## 3. Components

### 3.1 `el/shopify.py`

Single-file Admin REST client (2024-10).

```python
SHOPIFY_API_VERSION = "2024-10"

class ShopifyAdminProvider(Protocol):
    def list_themes(self) -> list[dict]: ...
    def get_main_theme_id(self) -> int | None: ...
    def update_theme_asset(self, theme_id: int, key: str, value: str) -> dict: ...
    def create_product(self, payload: dict, *, idempotency_key: str | None = None) -> dict: ...
    def find_product_by_handle(self, handle: str) -> dict | None: ...
```

`ShopifyRestProvider` implementation:
- `__init__` requires `SHOPIFY_STORE_DOMAIN` (e.g. `mystore.myshopify.com`) and `SHOPIFY_ADMIN_API_TOKEN`.
- Header `X-Shopify-Access-Token: <token>`, `Content-Type: application/json`.
- Base URL: `https://{domain}/admin/api/{version}`.
- Retry: up to 3 attempts on 429/5xx with exponential backoff (1s, 2s, 4s).
- Idempotency for `create_product`: pre-check via `find_product_by_handle(handle)`; if exists, return existing payload (treated as "ok, reused"). Handle is derived from `(run_id, product_name)` slug.
- All methods raise `ShopifyError` on persistent failure.

No SDK dependency — plain `requests`.

### 3.2 `el/nodes/generate_shopify_theme.py`

Calls Vertex Gemini with a structured prompt that asks for a strict JSON object (no markdown fences). On any failure (no LLM, parse error, missing keys), falls back to a deterministic theme derived from `niche`:

```python
{
  "name": f"{niche or 'EL'} Shop",
  "palette": {"primary":"#111827","secondary":"#374151","accent":"#f59e0b","bg":"#ffffff","text":"#111827"},
  "fonts": {"heading":"Inter, sans-serif", "body":"Inter, sans-serif"},
  "hero": {"headline": f"Shop {niche or 'today'}", "subhead":"Curated picks, hand-reviewed.", "cta":"Shop now"},
  "story_html": f"<p>Curated picks for {niche or 'today'}.</p>"
}
```

Always writes `ctx["shopify_theme"]`. Result key `ctx["shopify_theme_generation"] = {ok, source: "llm"|"fallback"}`.

### 3.3 `el/nodes/upload_shopify_theme.py`

- Resolves theme id: `ctx.get("shopify_theme_id")` → `provider.get_main_theme_id()`.
- Renders a single snippet `snippets/el-story.liquid` from the story HTML:
  ```
  <section class="el-story" style="background:{{ bg }};color:{{ text }};">
    <h2 style="font-family:{{ font_heading }};color:{{ primary }}">{{ headline }}</h2>
    <p style="font-family:{{ font_body }}">{{ subhead }}</p>
    <a href="/collections/all" style="background:{{ accent }};color:#fff;padding:12px 20px;display:inline-block">{{ cta }}</a>
    <div>{{ story_html }}</div>
  </section>
  ```
  (Built in Python and POSTed verbatim — Liquid placeholders pre-substituted.)
- Calls `provider.update_theme_asset(theme_id, "snippets/el-story.liquid", rendered)`.
- Failure → `ctx["shopify_theme_result"] = {"ok": False, "error": ...}` + `formatted_error`.
- Success → `ctx["shopify_theme_result"] = {"ok": True, "theme_id": ..., "asset_keys": ["snippets/el-story.liquid"]}`.

### 3.4 `el/nodes/upload_shopify_products.py`

For each pick in `ctx["hil_review_rows"]` (fallback `curated_picks`):

- `payload = {"product": {"title": product_name, "body_html": ..., "vendor": "EL", "tags": [...], "variants": [{"price": price_text or "0.00"}], "images": [{"src": image_url}] if image_url else []}}`
- Handle: `_slug(f"{run_request_id}-{product_name}")`.
- Call `provider.create_product(payload, idempotency_key=handle)`.
- Aggregate into `ctx["shopify_product_results"] = [...]`.
- On any failure: append single `formatted_error` line `f"upload_shopify_products: X/N failed"`.
- After loop, if any product succeeded, set `ctx["shopify_store_url"] = f"https://{SHOPIFY_STORE_DOMAIN}"`.

### 3.5 `el/nodes/notify_business.py` (update)

If `ctx.get("shopify_store_url")` present, append a third line `f"Store: {url}"` to the existing message. No other change.

## 4. Pipeline wiring (`el/pipeline.py`)

Inside the existing block that runs after HIL approve and after SP5a, add a new gated block:

```python
if (config.get("SHOPIFY_STORE_DOMAIN")
        and config.get("SHOPIFY_ADMIN_API_TOKEN")):
    generate_shopify_theme.run(ctx)
    upload_shopify_theme.run(ctx)
    upload_shopify_products.run(ctx)
else:
    log.warning("SHOPIFY_* not set — skipping Shopify auto-store")
```

This block runs **before** `notify_business.run(ctx)` so the store URL is in ctx when notify fires.

## 5. Data flow & shapes

- Input: `ctx["hil_review_rows"]` (preferred) or `ctx["curated_picks"]` (fallback), `ctx["niche"]`, `ctx["request_id"]`/`run_request_id`.
- Output keys added to ctx:
  - `shopify_theme`
  - `shopify_theme_generation`
  - `shopify_theme_result`
  - `shopify_product_results`
  - `shopify_store_url` (only if at least one product uploaded)

## 6. Error handling

- All nodes wrap the network call in `try/except Exception`.
- On failure: set `<key>_result = {"ok": False, "error": str(exc)}`, append to `formatted_error`, log via `log.exception`.
- No partial state leak: theme generation never raises (always at minimum returns fallback theme).
- `telegram_alert` already picks up `formatted_error` and fires post-`notify_business`.

## 7. Testing

`tests/test_shopify.py` — `ShopifyRestProvider` happy path + retry on 429 + idempotency via `find_product_by_handle`.

`tests/test_nodes_generate_shopify_theme.py` — LLM happy path returns parsed JSON; LLM raises → fallback; LLM returns non-JSON → fallback.

`tests/test_nodes_upload_shopify_theme.py` — happy path posts snippet; failure sets formatted_error.

`tests/test_nodes_upload_shopify_products.py` — all-ok / partial-failure aggregation / no picks no-op / falls-back-to-curated_picks / sets `shopify_store_url` when at least one succeeds.

`tests/test_nodes_notify_business.py` — extend with new test: when ctx has `shopify_store_url`, message contains `Store: <url>`.

All tests use Fake providers; zero live network.

## 8. Env vars (added to `.env.example` section 15)

```
SHOPIFY_STORE_DOMAIN=""            # e.g. "mystore.myshopify.com" (no protocol)
SHOPIFY_ADMIN_API_TOKEN=""         # custom app admin token
SHOPIFY_API_VERSION="2024-10"      # rarely changed
```

## 9. Out of scope (deferred)

- Collection creation / product-to-collection assignment.
- Inventory tracking (we set `track_inventory=false` implicitly; not in payload).
- Variants beyond a single price.
- Image upload via `images.json` (we pass `src` URL only; Shopify fetches it).
- Theme template replacement (we only inject one snippet — sites still need an operator to reference `{% render 'el-story' %}` in their theme; documented but not automated).
- CRM hook (SP6).

## 10. Files touched

| File | Action |
|---|---|
| `el/shopify.py` | new |
| `el/nodes/generate_shopify_theme.py` | new |
| `el/nodes/upload_shopify_theme.py` | new |
| `el/nodes/upload_shopify_products.py` | new |
| `el/nodes/__init__.py` | (empty file, no change needed) |
| `el/nodes/notify_business.py` | add store_url line |
| `el/pipeline.py` | import + wire 3 new nodes; gate on SHOPIFY env vars |
| `.env.example` | section 15 |
| `tests/test_shopify.py` | new |
| `tests/test_nodes_generate_shopify_theme.py` | new |
| `tests/test_nodes_upload_shopify_theme.py` | new |
| `tests/test_nodes_upload_shopify_products.py` | new |
| `tests/test_nodes_notify_business.py` | +1 test |
