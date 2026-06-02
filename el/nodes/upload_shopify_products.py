"""SP5b — push each approved pick as a Shopify product.

Handle (= idempotency key) is derived from the run id + product name so re-runs
of the same approved batch reuse existing products rather than duplicating.
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
    rows = ctx.get("hil_review_rows") or []
    if isinstance(rows, list) and rows:
        return [r for r in rows if isinstance(r, dict)]
    picks = ctx.get("curated_picks") or []
    return [p for p in picks if isinstance(p, dict) and "error" not in p]


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


def run(ctx: dict, *, provider: shopify.ShopifyAdminProvider | None = None) -> dict:
    picks = _picks(ctx)
    if not picks:
        ctx["shopify_product_results"] = []
        log.info("upload_shopify_products: no picks — skipping")
        return ctx

    niche = ctx.get("niche") or ""
    run_id = ctx.get("request_id") or ctx.get("run_request_id") or "run"

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

    results: list[dict] = []
    succeeded = 0
    for pick in picks:
        name = _name(pick)
        handle = _slug(f"{run_id}-{name}")
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
