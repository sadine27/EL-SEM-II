"""SP3 pipeline node: embed CJ top-3 candidates into private.product_embeddings.

Runs after pick_top_3. For each candidate:
  1. Compute product_key (lowercased product_url) and raw_payload_hash.
  2. Look up the existing row; if hash matches, skip (no Vertex re-spend).
  3. Otherwise call provider.embed_text + (optional) provider.embed_image.
  4. Upsert into private.product_embeddings (conflict on product_key).

Pipeline never crashes — every failure mode is caught and accounted for in
ctx["embeddings_result"].

Master flag EL_EMBEDDINGS_ENABLED=false → passthrough; no provider calls.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from el import config, embeddings, supabase
from el.logger import get_logger

log = get_logger(__name__)


def _enabled() -> bool:
    raw = config.get("EL_EMBEDDINGS_ENABLED", "true")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _product_key(product_url: str) -> str:
    return (product_url or "").strip().lower()


def _first_image(candidate: dict) -> str | None:
    raw = candidate.get("image_urls")
    if isinstance(raw, list):
        images = raw
    elif isinstance(raw, str):
        try:
            images = json.loads(raw)
        except Exception:
            images = []
    else:
        images = []
    if not isinstance(images, list):
        return None
    for img in images:
        if isinstance(img, str) and img.strip():
            return img.strip()
    return None


def _raw_payload_hash(candidate: dict) -> str:
    parts = [
        str(candidate.get("product_name") or ""),
        str(candidate.get("product_url") or ""),
        str(_first_image(candidate) or ""),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def _existing_hashes(
    db: Any, schema: str, table: str, product_keys: list[str]
) -> dict[str, str]:
    """Return {product_key: raw_payload_hash} for any existing rows."""
    if not product_keys:
        return {}
    keys_quoted = ",".join(f'"{k}"' for k in product_keys)
    try:
        rows = db.select_rows(
            schema=schema,
            table=table,
            filters={"product_key": f"in.({keys_quoted})"},
            select="product_key,raw_payload_hash",
        )
    except Exception:
        log.exception("embed_candidate_products: failed to read existing hashes — embedding all")
        return {}
    return {
        r["product_key"]: r.get("raw_payload_hash")
        for r in rows
        if isinstance(r, dict) and r.get("product_key")
    }


def _embed_one(provider, candidate: dict) -> tuple[list[float] | None, list[float] | None]:
    """Return (text_vec, image_vec) for a candidate; raises EmbeddingError on text fail."""
    text = (candidate.get("product_name") or "").strip()
    text_vec = provider.embed_text(text) if text else None

    image_vec: list[float] | None = None
    img_url = _first_image(candidate)
    if img_url:
        try:
            image_vec = provider.embed_image(img_url)
        except Exception:
            log.warning(
                "embed_candidate_products: image embed failed for %s — storing NULL image_embedding",
                img_url,
            )
            image_vec = None
    return text_vec, image_vec


def run(
    ctx: dict,
    *,
    provider: embeddings.EmbeddingProvider | None = None,
    db_provider: Any | None = None,
) -> dict:
    if not _enabled():
        candidates = ctx.get("cj_top_products") or []
        ctx["embeddings_result"] = {
            "ok": True,
            "embedded_n": 0,
            "skipped_n": len(candidates),
            "failed_n": 0,
            "reason": "EL_EMBEDDINGS_ENABLED=false",
        }
        log.info("embed_candidate_products: disabled by EL_EMBEDDINGS_ENABLED")
        return ctx

    candidates = ctx.get("cj_top_products") or []
    if not candidates:
        ctx["embeddings_result"] = {"ok": True, "embedded_n": 0, "skipped_n": 0, "failed_n": 0}
        return ctx

    active_provider = provider or embeddings.VertexEmbeddingProvider()
    active_db = db_provider or supabase.SupabaseRestProvider()

    keys = [_product_key(c.get("product_url") or "") for c in candidates if isinstance(c, dict)]
    existing = _existing_hashes(
        active_db, supabase.HIL_REVIEWS_SCHEMA, supabase.PRODUCT_EMBEDDINGS_TABLE, keys,
    )

    rows_to_upsert: list[dict] = []
    embedded_n = 0
    skipped_n = 0
    failed_n = 0

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        url = candidate.get("product_url") or ""
        key = _product_key(url)
        h = _raw_payload_hash(candidate)
        if existing.get(key) == h:
            skipped_n += 1
            continue
        try:
            text_vec, image_vec = _embed_one(active_provider, candidate)
        except Exception:
            log.exception("embed_candidate_products: provider failed for %s", key)
            failed_n += 1
            continue
        if text_vec is None:
            failed_n += 1
            continue
        rows_to_upsert.append({
            "product_key": key,
            "product_url": url,
            "product_sku": candidate.get("product_sku"),
            "product_name": candidate.get("product_name") or "",
            "image_url": _first_image(candidate),
            "text_embedding": text_vec,
            "image_embedding": image_vec,
            "source_provider": candidate.get("source_provider"),
            "raw_payload_hash": h,
        })
        embedded_n += 1

    if not rows_to_upsert:
        ctx["embeddings_result"] = {
            "ok": True, "embedded_n": embedded_n,
            "skipped_n": skipped_n, "failed_n": failed_n,
        }
        return ctx

    try:
        active_db.upsert_rows(
            schema=supabase.HIL_REVIEWS_SCHEMA,
            table=supabase.PRODUCT_EMBEDDINGS_TABLE,
            rows=rows_to_upsert,
            conflict_columns=supabase.PRODUCT_EMBEDDINGS_CONFLICT_COLUMNS,
        )
    except Exception as exc:
        log.exception("embed_candidate_products: upsert failed")
        ctx["embeddings_result"] = {
            "ok": False,
            "embedded_n": embedded_n,
            "skipped_n": skipped_n,
            "failed_n": failed_n,
            "error": str(exc),
        }
        return ctx

    ctx["embeddings_result"] = {
        "ok": True,
        "embedded_n": embedded_n,
        "skipped_n": skipped_n,
        "failed_n": failed_n,
    }
    log.info(
        "embed_candidate_products: embedded=%d skipped=%d failed=%d",
        embedded_n, skipped_n, failed_n,
    )
    return ctx
