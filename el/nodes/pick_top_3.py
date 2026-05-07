"""Port of n8n node `Pick Top 3`."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from el.logger import get_logger

log = get_logger(__name__)


def parse_price(value: object) -> float | None:
    if not value:
        return None
    nums = re.findall(r"[\d.]+", str(value))
    if not nums:
        return None
    try:
        return float(nums[0])
    except ValueError:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _product_name(product: dict) -> str:
    return str(product.get("productNameEn") or product.get("productName") or "")


def _listed_num(product: dict) -> float:
    try:
        return float(product.get("listedNum") or 0)
    except (TypeError, ValueError):
        return 0.0


def pick_products(response: dict, query: dict, limit: int = 3) -> list[dict]:
    if not isinstance(response, dict):
        return []
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    products = data.get("list") or []
    if not isinstance(products, list):
        return []
    products = [product for product in products if isinstance(product, dict)]
    if not isinstance(query, dict):
        query = {}
    tokens = [w for w in str(query.get("keyword") or "").split() if len(w) > 2]
    strict = [
        product for product in products
        if any(token in _product_name(product).lower() for token in tokens)
    ]
    strict.sort(key=_listed_num, reverse=True)
    top = strict[:limit]
    if len(top) < limit:
        seen = {product.get("pid") for product in top}
        rest = [
            product for product in products
            if product.get("pid") not in seen
        ]
        rest.sort(key=_listed_num, reverse=True)
        top = top + rest[:limit - len(top)]
    return top


def normalize_product(product: dict, query: dict, scraped_at: str | None = None) -> dict:
    pid = product.get("pid")
    images = [img for img in str(product.get("productImage") or "").split(";") if img]
    return {
        "run_date": query.get("run_date"),
        "source_topic": query.get("source_topic"),
        "source_pick_rank": query.get("source_pick_rank"),
        "opportunity_score": query.get("opportunity_score"),
        "source_provider": "cj_dropshipping",
        "product_name": product.get("productNameEn") or product.get("productName"),
        "product_url": f"https://app.cjdropshipping.com/product/{pid}.html",
        "product_sku": product.get("productSku"),
        "price_text": str(product.get("sellPrice") or ""),
        "price_numeric": parse_price(product.get("sellPrice")),
        "currency": "USD",
        "description": "",
        "image_urls": json.dumps(images),
        "offers": json.dumps([{
            "listedNum": product.get("listedNum") or 0,
            "supplierName": product.get("supplierName"),
            "isFreeShipping": bool(product.get("isFreeShipping")),
            "shippingCountryCodes": product.get("shippingCountryCodes"),
            "categoryName": product.get("categoryName"),
        }]),
        "raw_payload": json.dumps(product),
        "scraped_at": scraped_at or _now_iso(),
    }


def run(ctx: dict) -> dict:
    items = ctx.get("cj_product_list_responses") or []
    rows = []
    scraped_at = _now_iso()
    for item in items:
        if not isinstance(item, dict):
            continue
        if not item.get("ok", True):
            continue
        query = item.get("query") or {}
        response = item.get("response") or {}
        rows.extend(
            normalize_product(product, query, scraped_at=scraped_at)
            for product in pick_products(response, query)
        )
    ctx["cj_top_products"] = rows
    log.info("Pick Top 3: selected %d CJ products", len(rows))
    return ctx
