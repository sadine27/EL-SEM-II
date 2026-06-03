"""Forge supplier adapter: real Indian marketplace listings.

CJ Dropshipping is a global generic catalog — it never carries India-viral
items (e.g. an "RCB IPL jersey"). This source instead finds the *actual product*
on Indian marketplaces (Amazon.in / Flipkart / Meesho) for any trend, using:

    Tavily web search  ->  (Browserbase fetch for thin pages)  ->  Gemini extract

It returns a ``SupplierCandidate`` with the real title, image URL, INR price,
rating, and the marketplace source URL for provenance.

This is a **demo/academic listing** source: it sources real-looking product
data, not real dropship fulfillment, so scraping public marketplace pages is in
scope. Every external call is wrapped: any failure yields fewer/zero candidates,
never an exception.
"""
from __future__ import annotations

import json
import re
from typing import Any

from el import config
from el.logger import get_logger
from el.suppliers import SupplierCandidate

log = get_logger(__name__)

SOURCE_ID = "marketplace"

_MARKETPLACE_DOMAINS = ("amazon.in", "flipkart.com", "meesho.com", "ajio.com", "myntra.com")
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_MAX_PAGES_PER_TREND = 3

_SYSTEM = (
    "You extract one product listing from raw Indian marketplace page text. "
    "Return ONLY a JSON object:\n"
    '{"title": "<product title>", "price_inr": <number or null>, '
    '"image_url": "<direct product image URL or null>", '
    '"rating": <number 0..5 or null>, "in_stock": <bool>, '
    '"description": "<one-sentence description>"}\n'
    "price_inr is the selling price in rupees as a plain number (no symbols/commas). "
    "image_url must be a real URL found in the text, else null. "
    "No commentary outside the JSON object."
)


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", (text or "").strip())


def _int_config(name: str, default: int) -> int:
    raw = config.get(name)
    try:
        return max(0, int(str(raw).strip())) if raw is not None else default
    except ValueError:
        return default


def _is_marketplace(url: str) -> bool:
    u = (url or "").lower()
    return any(dom in u for dom in _MARKETPLACE_DOMAINS)


def _parse_obj(raw: str) -> dict:
    text = _strip_fences(raw)
    if not text:
        return {}
    if not text.lstrip().startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    nums = re.findall(r"[\d.]+", str(value).replace(",", ""))
    try:
        return float(nums[0]) if nums else None
    except ValueError:
        return None


class MarketplaceSource:
    SOURCE_ID = SOURCE_ID

    def __init__(self, *, tavily=None, browserbase=None, provider=None):
        self._tavily = tavily
        self._browserbase = browserbase
        self._provider = provider

    # --- lazy provider wiring (kept out of __init__ so import never needs creds) ---
    def _get_tavily(self):
        if self._tavily is None:
            from el import tavily as tavily_mod
            self._tavily = tavily_mod.default_provider()
        return self._tavily

    def _get_browserbase(self):
        if self._browserbase is None and config.get("BROWSERBASE_API_KEY"):
            from el import browserbase
            self._browserbase = browserbase.BrowserbaseProvider()
        return self._browserbase

    def _get_provider(self):
        if self._provider is None:
            from el import llm
            self._provider = llm.default_provider()
        return self._provider

    def _credentials_available(self) -> bool:
        return bool(config.get("TAVILY_API_KEY") and config.get("GOOGLE_SERVICE_ACCOUNT_JSON"))

    def _page_text(self, result: dict) -> str:
        """Prefer Tavily raw_content; fall back to Browserbase fetch for thin pages."""
        text = (result.get("raw_content") or result.get("content") or "").strip()
        if len(text) >= 500:
            return text[:8000]
        bb = self._get_browserbase()
        if bb is not None:
            fetched = bb.fetch(result.get("url", ""))
            if fetched.get("ok") and fetched.get("content"):
                return str(fetched["content"])[:8000]
        return text[:8000]

    def _extract(self, query: str, result: dict) -> SupplierCandidate | None:
        page_text = self._page_text(result)
        if not page_text:
            return None
        user = f"Trend/query: {query}\nMarketplace URL: {result.get('url','')}\n\nPAGE TEXT:\n{page_text}"
        try:
            raw = self._get_provider().generate(_SYSTEM, user)
        except Exception as exc:
            log.warning("marketplace: extraction LLM call failed soft: %s", exc)
            return None
        obj = _parse_obj(raw)
        title = str(obj.get("title") or result.get("title") or "").strip()
        if not title:
            return None
        return SupplierCandidate(
            title=title,
            source_id=SOURCE_ID,
            product_url=result.get("url"),
            image_url=(str(obj["image_url"]).strip() if obj.get("image_url") else None),
            cost=_to_float(obj.get("price_inr")),
            currency="INR",
            shipping_cost=0.0,
            stock=1 if obj.get("in_stock", True) else 0,
            rating=_to_float(obj.get("rating")),
            raw_payload={
                "marketplace": next((d for d in _MARKETPLACE_DOMAINS if d in (result.get("url") or "")), ""),
                "description": str(obj.get("description") or "").strip(),
                "source_url": result.get("url"),
            },
        )

    def search_products(self, query: str, ctx: dict) -> list[SupplierCandidate]:
        if not query or not self._credentials_available():
            if not self._credentials_available():
                log.info("marketplace: EMPTY (no key) — TAVILY_API_KEY / GOOGLE_SERVICE_ACCOUNT_JSON not set")
            return []

        try:
            search = self._get_tavily().search(
                f"buy {query} online India price", max_results=8, include_raw_content=True,
            )
        except Exception as exc:
            log.warning("marketplace: tavily search failed soft: %s", exc)
            return []
        if not search.get("ok"):
            return []

        marketplace_hits = [r for r in search.get("results", []) if _is_marketplace(r.get("url", ""))]
        marketplace_hits = marketplace_hits[: _int_config("EL_MARKETPLACE_MAX_PAGES", _MAX_PAGES_PER_TREND)]

        candidates: list[SupplierCandidate] = []
        for result in marketplace_hits:
            cand = self._extract(query, result)
            if cand is not None:
                candidates.append(cand)

        log.info(
            "marketplace: %s — %d listing(s) for %r (%d marketplace hits)",
            "OK" if candidates else "EMPTY", len(candidates), query, len(marketplace_hits),
        )
        return candidates


def default_source() -> MarketplaceSource:
    return MarketplaceSource()
