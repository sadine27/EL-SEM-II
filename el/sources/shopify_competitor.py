"""Trend source: Shopify competitor stores via the public /products.json endpoint.

Configured via:
  EL_SHOPIFY_COMPETITOR_STORES       comma-separated store URLs
  EL_SHOPIFY_COMPETITOR_MAX_PAGES    pagination cap per store (default 4)

Each store URL is queried at `<url>/products.json?limit=250&page=N` for N=1..max.
Pagination stops on the first empty page. Per-store errors (HTTP, JSON, timeout)
are caught and logged; one bad store never affects the others. The function
never raises across the protocol boundary — failures yield [] for that store.
"""
from __future__ import annotations

from urllib.parse import urlparse

import requests

from el import config
from el.logger import get_logger
from el.sources import TrendCandidate

SOURCE_ID = "shopify_competitor"

DEFAULT_TIMEOUT = 30
PRODUCTS_PER_PAGE = 250
DEFAULT_MAX_PAGES = 4

log = get_logger(__name__)


def _store_urls() -> list[str]:
    raw = config.get("EL_SHOPIFY_COMPETITOR_STORES") or ""
    return [u.strip().rstrip("/") for u in raw.split(",") if u.strip()]


def _max_pages() -> int:
    raw = config.get("EL_SHOPIFY_COMPETITOR_MAX_PAGES")
    if not raw:
        return DEFAULT_MAX_PAGES
    try:
        n = int(raw)
        return max(1, n)
    except ValueError:
        log.warning("Invalid EL_SHOPIFY_COMPETITOR_MAX_PAGES=%r — using %d", raw, DEFAULT_MAX_PAGES)
        return DEFAULT_MAX_PAGES


def _store_handle(url: str) -> str:
    """Extract a stable identifier from the store URL: first label of the hostname."""
    host = urlparse(url).hostname or url
    return host.split(".")[0]


def _fetch_one_store(url: str, max_pages: int) -> list[TrendCandidate]:
    handle = _store_handle(url)
    source_id = f"{SOURCE_ID}:{handle}"
    out: list[TrendCandidate] = []
    for page in range(1, max_pages + 1):
        try:
            resp = requests.get(
                f"{url}/products.json",
                params={"limit": PRODUCTS_PER_PAGE, "page": page},
                timeout=DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001 — HTTP boundary fails soft
            log.warning("shopify_competitor[%s]: page %d failed: %s", handle, page, exc)
            return out
        products = payload.get("products") if isinstance(payload, dict) else None
        if not products:
            return out
        for product in products:
            if not isinstance(product, dict):
                continue
            title = product.get("title")
            if not title:
                continue
            out.append(TrendCandidate(
                title=str(title),
                source_id=source_id,
                raw_payload=product,
            ))
        if len(products) < PRODUCTS_PER_PAGE:
            # Partial page → no more results.
            return out
    return out


def fetch_trends(ctx: dict) -> list[TrendCandidate]:
    urls = _store_urls()
    if not urls:
        return []
    max_pages = _max_pages()
    candidates: list[TrendCandidate] = []
    for url in urls:
        try:
            candidates.extend(_fetch_one_store(url, max_pages))
        except Exception:
            log.exception("shopify_competitor: unexpected failure on %s", url)
    log.info("shopify_competitor: fetched %d candidates from %d store(s)", len(candidates), len(urls))
    return candidates
