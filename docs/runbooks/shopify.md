# Shopify Runbook

## Required Environment

Set `SHOPIFY_STORE_DOMAIN` plus one Shopify Admin auth mode:

- `SHOPIFY_ADMIN_API_TOKEN`
- or `SHOPIFY_CLIENT_ID` and `SHOPIFY_CLIENT_SECRET`

Optional:

- `SHOPIFY_API_VERSION` defaults to the version in `el/shopify.py`.

## Smoke Test

Run the live Shopify smoke test before tagging a release:

```sh
make shopify-smoke
```

The smoke test:

1. Lists themes and prints the main theme id.
2. Temporarily writes a sentinel to `assets/tokens.css`.
3. Reads `assets/tokens.css` back and verifies the sentinel round-trips.
4. Creates a draft throwaway product with handle `el-smoke-test-<unix_ts>`.
5. Deletes the throwaway product.
6. Restores the prior `assets/tokens.css` value.

The command exits non-zero on any failed step. If a later step fails after
writing the theme asset or creating the product, the script attempts cleanup in
`finally` before exiting.
