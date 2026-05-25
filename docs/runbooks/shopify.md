# Shopify Runbook

This runbook covers the live Shopify setup used by `el/shopify.py`,
`el/nodes/upload_shopify_theme.py`, and `scripts/shopify_smoke.py`.

## Dev Store And App

1. Create or open a Shopify Partner account.
2. Create a development store for EL testing.
3. In the dev store admin, create a custom app.
4. Configure Admin API access scopes:
   - `read_themes`
   - `write_themes`
   - `read_products`
   - `write_products`
5. Install the custom app on the dev store.

Use the store domain in the `*.myshopify.com` form, for example
`example-dev.myshopify.com`.

## Auth Choice

Preferred local and CI auth is `SHOPIFY_ADMIN_API_TOKEN`.

The Admin API access token is shown after installing the custom app. It is the
simplest path because `ShopifyRestProvider._access_token()` returns it directly
and never calls `/admin/oauth/access_token`.

Client credentials are the fallback path. Find the custom app API key and API
secret key in the app credentials screen, then set `SHOPIFY_CLIENT_ID` and
`SHOPIFY_CLIENT_SECRET`. The provider exchanges them for an access token and
caches it until `expires_in - 60` seconds.

## First Theme Setup

The trusted section shells are developer-owned static infrastructure under:

```text
el/assets/theme_shells/sections/
```

The current shell section types come from `SECTION_TYPE_BY_ID` in
`el/nodes/upload_shopify_theme.py`:

- `hero-shell`
- `featured-collections-shell`
- `product-grid-shell`
- `promo-shell`
- `footer-shell`

On first upload to a fresh theme, `upload_shopify_theme.run()` reads those local
files and uploads each fixed path as `sections/<name>.liquid` only if the asset
does not already exist. AI output is never allowed to choose shell paths or
generate Liquid/schema. AI-generated theme uploads remain limited to:

- `assets/tokens.css`
- `templates/index.json`

## Environment

| Variable | Required | Notes |
| --- | --- | --- |
| `SHOPIFY_STORE_DOMAIN` | Yes | Dev store domain, without `https://`. |
| `SHOPIFY_ADMIN_API_TOKEN` | Preferred | Admin API access token from the installed custom app. |
| `SHOPIFY_CLIENT_ID` | Fallback | Custom app API key; requires `SHOPIFY_CLIENT_SECRET`. |
| `SHOPIFY_CLIENT_SECRET` | Fallback | Custom app API secret; requires `SHOPIFY_CLIENT_ID`. |
| `SHOPIFY_API_VERSION` | No | Defaults to the version in `el/shopify.py`. |

## Smoke Test

Before tagging a release, run:

```sh
make shopify-smoke
```

The smoke test lists themes, writes and verifies a sentinel in
`assets/tokens.css`, creates and deletes a draft throwaway product, then restores
the prior `assets/tokens.css` value. It exits non-zero on failure and attempts
cleanup in `finally`.

## Rollback

`el/nodes/upload_shopify_theme.py::run()` fetches each current AI-managed asset
before updating it and stores prior values in:

```python
ctx["shopify_theme_backup"] = {key: prior_value}
```

Only `assets/tokens.css` and `templates/index.json` are backed up this way. To
roll back a failed theme upload, use the same Shopify provider and write each
backup value back to the same theme id:

```python
for key, value in ctx["shopify_theme_backup"].items():
    provider.update_theme_asset(theme_id, key, value)
```

Trusted shell sections are uploaded only when missing and are not overwritten by
the node, so rollback normally applies only to the two AI-managed assets above.
