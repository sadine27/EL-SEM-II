"""Live Shopify smoke test.

Run:
    python scripts/shopify_smoke.py
"""
from __future__ import annotations

import os
import sys
import time

from el import shopify


TOKENS_KEY = "assets/tokens.css"
SENTINEL_PREFIX = "/* el-shopify-smoke-test "


def _require_env() -> None:
    missing = []
    if not os.getenv("SHOPIFY_STORE_DOMAIN"):
        missing.append("SHOPIFY_STORE_DOMAIN")
    has_admin_token = bool(os.getenv("SHOPIFY_ADMIN_API_TOKEN"))
    has_client_credentials = bool(
        os.getenv("SHOPIFY_CLIENT_ID") and os.getenv("SHOPIFY_CLIENT_SECRET")
    )
    if not has_admin_token and not has_client_credentials:
        missing.append(
            "SHOPIFY_ADMIN_API_TOKEN or SHOPIFY_CLIENT_ID + SHOPIFY_CLIENT_SECRET"
        )
    if missing:
        raise shopify.ShopifyError("missing required env: " + ", ".join(missing))


def _ok(message: str) -> None:
    print(f"[OK] {message}")


def main() -> int:
    provider: shopify.ShopifyRestProvider | None = None
    theme_id: int | None = None
    prior_tokens: str | None = None
    touched_tokens = False
    product_id: int | None = None

    try:
        _require_env()
        provider = shopify.ShopifyRestProvider()

        themes = provider.list_themes()
        main_theme = next((theme for theme in themes if theme.get("role") == "main"), None)
        if not main_theme:
            raise shopify.ShopifyError("no main theme found")
        theme_id = int(main_theme["id"])
        print(f"main theme id: {theme_id}")

        prior_asset = provider.get_theme_asset(theme_id, TOKENS_KEY)
        prior_tokens = prior_asset.get("value") if isinstance(prior_asset, dict) else None
        if prior_tokens is None:
            raise shopify.ShopifyError(f"{TOKENS_KEY} does not exist; refusing smoke overwrite")

        sentinel = f"{SENTINEL_PREFIX}{int(time.time())} */\n:root {{ --el-smoke-test: 1; }}\n"
        provider.update_theme_asset(theme_id, TOKENS_KEY, sentinel)
        touched_tokens = True
        _ok(f"updated {TOKENS_KEY} with sentinel")

        round_trip = provider.get_theme_asset(theme_id, TOKENS_KEY)
        if round_trip.get("value") != sentinel:
            raise shopify.ShopifyError(f"{TOKENS_KEY} sentinel did not round-trip")
        _ok(f"{TOKENS_KEY} sentinel round-tripped")

        unix_ts = int(time.time())
        handle = f"el-smoke-test-{unix_ts}"
        if provider.find_product_by_handle(handle) is not None:
            raise shopify.ShopifyError(f"smoke product handle already exists: {handle}")
        product = provider.create_product(
            {
                "product": {
                    "title": f"EL Smoke Test {unix_ts}",
                    "body_html": "<p>Temporary smoke-test product. Safe to delete.</p>",
                    "vendor": "EL",
                    "status": "draft",
                    "tags": "el-smoke-test",
                    "variants": [{"price": "0.00"}],
                }
            },
            idempotency_key=handle,
        )
        product_id = int(product["id"])
        _ok(f"created throwaway product {product_id} ({handle})")

        provider.delete_product(product_id)
        product_id = None
        _ok("deleted throwaway product")

        provider.update_theme_asset(theme_id, TOKENS_KEY, prior_tokens)
        touched_tokens = False
        _ok(f"restored {TOKENS_KEY}")
        return 0
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    finally:
        if provider is not None and product_id is not None:
            try:
                provider.delete_product(product_id)
                print("[OK] cleaned up throwaway product")
            except Exception as exc:
                print(f"[WARN] failed to clean up product {product_id}: {exc}", file=sys.stderr)
        if provider is not None and theme_id is not None and touched_tokens and prior_tokens is not None:
            try:
                provider.update_theme_asset(theme_id, TOKENS_KEY, prior_tokens)
                print(f"[OK] restored {TOKENS_KEY} after failure")
            except Exception as exc:
                print(f"[WARN] failed to restore {TOKENS_KEY}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
