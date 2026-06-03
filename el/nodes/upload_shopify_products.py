"""SP5b — push each approved pick as a Shopify product.

Each run clears the store first so stale products never accumulate, then
uploads the current slate. Handle is derived from product_name only (no
run id) so the same product across runs reuses the same slot cleanly.
"""
from __future__ import annotations

import re

from el import config, shopify
from el.logger import get_logger

log = get_logger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def _slug(text: str) -> str:
    s = (text or "").strip().lower().replace("_", "-").replace(" ", "-")
    s = _SLUG_RE.sub("", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "el-product"


def _picks(ctx: dict) -> list[dict]:
    hil = ctx.get("hil_review_rows")
    if hil is not None:
        # HIL path: only upload rows that were explicitly approved by the human reviewer.
        # pending/rejected rows must never reach Shopify.
        return [
            r for r in hil
            if isinstance(r, dict) and r.get("product_name") and r.get("approval_status") == "approved"
        ]
    # Fallback: curated_picks when HIL is disabled (topic title is acceptable)
    rows = ctx.get("curated_picks") or []
    return [r for r in rows if isinstance(r, dict)]


def _name(pick: dict) -> str:
    return (
        pick.get("product_name")
        or pick.get("topic")
        or pick.get("title")
        or "Untitled"
    )


def _price(pick: dict) -> str:
    price = pick.get("price_text") or pick.get("price") or pick.get("price_numeric")
    if price is None or price == "":
        return "0.00"
    return str(price)


def _payload(pick: dict, *, niche: str) -> dict:
    name = _name(pick)
    desc = pick.get("description") or pick.get("reason") or ""
    body_html = f"<p>{desc}</p>" if desc else f"<p>{name}</p>"
    images = []
    img = pick.get("image_url")
    if img:
        images.append({"src": img})
    tags = ["el-curated"]
    if niche:
        tags.append(niche.replace(",", " ").strip())
    variant = {"price": _price(pick)}
    return {
        "product": {
            "title": name,
            "body_html": body_html,
            "vendor": "EL",
            "tags": ", ".join(tags),
            "variants": [variant],
            "images": images,
        }
    }


def _clear_existing_products(provider: shopify.ShopifyAdminProvider) -> None:
    try:
        products = provider.list_products()
        for p in products:
            try:
                provider.delete_product(int(p["id"]))
            except Exception:
                log.warning("upload_shopify_products: could not delete product %s", p.get("id"))
        log.info("upload_shopify_products: cleared %d existing product(s)", len(products))
    except Exception:
        log.exception("upload_shopify_products: clear step failed — continuing with upload")


def create_one(
    row: dict,
    *,
    niche: str = "",
    provider: shopify.ShopifyAdminProvider | None = None,
) -> dict:
    """Create a single Shopify product for an approved HIL review row.

    Does NOT clear existing products — used by the HIL poller callback path
    to add a product the moment it is approved, rather than in the batch run.
    """
    if provider is None:
        try:
            provider = shopify.default_provider()
        except Exception as exc:
            log.warning("upload_shopify_products.create_one: provider init failed: %s", exc)
            return {"ok": False, "error": str(exc)}
    name = _name(row)
    handle = _slug(name)
    try:
        product = provider.create_product(_payload(row, niche=niche), idempotency_key=handle)
        log.info("upload_shopify_products.create_one: created %s (id=%s)", name, product.get("id"))
        return {"ok": True, "pick_name": name, "handle": handle, "product_id": product.get("id")}
    except Exception as exc:
        log.warning("upload_shopify_products.create_one: %s failed: %s", name, exc)
        return {"ok": False, "pick_name": name, "handle": handle, "error": str(exc)}


def run(ctx: dict, *, provider: shopify.ShopifyAdminProvider | None = None) -> dict:
    picks = _picks(ctx)
    if not picks:
        ctx["shopify_product_results"] = []
        log.info("upload_shopify_products: no picks — skipping")
        return ctx

    niche = ctx.get("niche") or ""

    if provider is None:
        try:
            provider = shopify.default_provider()
        except Exception as exc:
            ctx["shopify_product_results"] = []
            ctx.setdefault("formatted_error", []).append(
                {"text": f"upload_shopify_products: provider init failed: {exc}"}
            )
            log.exception("upload_shopify_products: provider init failed")
            return ctx

    _clear_existing_products(provider)

    results: list[dict] = []
    succeeded = 0
    for pick in picks:
        name = _name(pick)
        handle = _slug(name)
        try:
            product = provider.create_product(_payload(pick, niche=niche), idempotency_key=handle)
            results.append({
                "ok": True,
                "pick_name": name,
                "handle": handle,
                "product_id": product.get("id"),
            })
            succeeded += 1
        except Exception as exc:
            results.append({"ok": False, "pick_name": name, "handle": handle, "error": str(exc)})
            log.exception("upload_shopify_products: %s failed", name)

    ctx["shopify_product_results"] = results
    failed = [r for r in results if not r["ok"]]
    if failed:
        ctx.setdefault("formatted_error", []).append(
            {"text": f"upload_shopify_products: {len(failed)}/{len(results)} failed"}
        )

    if succeeded > 0:
        domain = config.get("SHOPIFY_STORE_DOMAIN", "").strip().rstrip("/")
        if domain:
            ctx["shopify_store_url"] = f"https://{domain}"
    log.info("upload_shopify_products: %d/%d ok", succeeded, len(results))
    return ctx
