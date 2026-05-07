"""Port of n8n node `Bundle JSON (Scraped)`.

Aggregates `ctx["cj_top_products"]` into a single JSON file (n8n-style binary
item) for Drive Upload (Scraped).
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

from el.logger import get_logger

log = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def run(ctx: dict) -> dict:
    products = [p for p in (ctx.get("cj_top_products") or []) if isinstance(p, dict)]
    run_date = (products[0].get("run_date") if products else None) or _today()
    providers = sorted({
        p.get("source_provider") for p in products if p.get("source_provider")
    })
    payload = {
        "metadata": {
            "run_date": run_date,
            "total_products": len(products),
            "scraped_at": _now_iso(),
            "source_providers": providers,
        },
        "products": products,
    }
    filename = f"scraped_products_{run_date}.json"
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    ctx["scraped_json_file"] = {
        "json": {"filename": filename, "total": len(products)},
        "binary": {
            "data": {
                "data": encoded,
                "mimeType": "application/json",
                "fileName": filename,
                "fileExtension": "json",
            }
        },
    }
    log.info("Bundle JSON (Scraped): bundled %d products into %s", len(products), filename)
    return ctx
