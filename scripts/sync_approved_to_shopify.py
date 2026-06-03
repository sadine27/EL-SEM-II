"""One-shot: clear Shopify store and upload all approved HIL products.

Run with:
    $env:EL_ENV_FILE = ".env"; docker compose run --rm worker python scripts/sync_approved_to_shopify.py

Deduplicates by product_url (keeps the most-recently-approved copy).
Clears all existing Shopify products first, then uploads the approved set.
"""
from __future__ import annotations

import sys

from el import shopify
from el.logger import get_logger
from el.nodes.upload_shopify_products import _clear_existing_products, create_one
from el.supabase import HIL_REVIEWS_SCHEMA, HIL_REVIEWS_TABLE, SupabaseRestProvider

log = get_logger(__name__)


def main() -> None:
    db = SupabaseRestProvider()

    # Fetch all approved rows, sorted newest first so dedup keeps the freshest copy
    rows = db.select_rows(
        schema=HIL_REVIEWS_SCHEMA,
        table=HIL_REVIEWS_TABLE,
        filters={"approval_status": "eq.approved", "order": "reviewed_at.desc"},
        limit=100,
    )

    # Deduplicate by product_url — keep first occurrence (= most recently approved)
    seen: set[str] = set()
    unique: list[dict] = []
    for row in rows:
        key = row.get("product_url") or row.get("product_name") or ""
        if key and key not in seen:
            seen.add(key)
            unique.append(row)

    print(f"Found {len(rows)} approved rows → {len(unique)} unique products after dedup")
    if not unique:
        print("Nothing to upload — exiting.")
        sys.exit(0)

    provider = shopify.default_provider()

    print("Clearing existing Shopify products...")
    _clear_existing_products(provider)

    ok = 0
    fail = 0
    for row in unique:
        result = create_one(row, provider=provider)
        status = "✓" if result["ok"] else "✗"
        msg = result.get("product_id") or result.get("error", "")
        print(f"  {status} {result.get('pick_name', '')[:60]}  (id={msg})")
        if result["ok"]:
            ok += 1
        else:
            fail += 1

    print(f"\nDone: {ok} uploaded, {fail} failed.")


if __name__ == "__main__":
    main()
