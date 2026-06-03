"""Forge supplier adapter: real Indian marketplace listings.

CJ Dropshipping is a global generic catalog — it never carries India-viral
items (e.g. an "RCB IPL jersey"). This source instead finds the *actual product*
on Indian marketplaces (Amazon.in / Flipkart / Meesho / Myntra / Ajio) for any
trend, and extracts clean structured data:

    Tavily web search
      -> fast page fetch -> JSON-LD Product schema (title/price/image/rating)
      -> LLM fallback on visible text  (-> Browserbase only if the page is blocked)

It returns a ``SupplierCandidate`` with real title, image URL, INR price,
rating, and the marketplace source URL for provenance.

This is a **demo/academic listing** source: real-looking product data, not real
dropship fulfillment, so scraping public marketplace pages is in scope. Every
external call is wrapped: any failure yields fewer/zero candidates, never raises.
"""
from __future__ import annotations

import json
import re
from typing import Any

import requests

from el import config
from el.logger import get_logger
from el.suppliers import SupplierCandidate

log = get_logger(__name__)

SOURCE_ID = "marketplace"

_MARKETPLACE_DOMAINS = ("amazon.in", "flipkart.com", "meesho.com", "ajio.com", "myntra.com")
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_MAX_PAGES_PER_TREND = 3
_FETCH_TIMEOUT = 12

# Believable-economics simulation (this is a demo listing source, not real
# fulfillment): the scraped price is the *retail* price a shopper pays. We keep
# it as the sell-side market reference and back-infer a plausible wholesale cost
# so Sentinel can compute a real, believable margin instead of a circular markup.
_DEFAULT_COST_FACTOR = 0.55        # wholesale cost ≈ 55% of retail → ~45% margin
_DEFAULT_SHIP_DAYS_MIN = 3
_DEFAULT_SHIP_DAYS_MAX = 7

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}

# Only unambiguous search/listing URLs are excluded. Marketplace slugs vary a lot
# (Flipkart /q/, Myntra bare slugs), so we keep anything that isn't a clear search
# results page and let JSON-LD presence decide product quality downstream.
_SEARCH_URL_HINTS = ("/s?", "/search?", "/search/", "&search=", "?q=")

_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)

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


def _flag(name: str, default: bool) -> bool:
    raw = config.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _float_config(name: str, default: float) -> float:
    raw = config.get(name)
    try:
        return float(str(raw).strip()) if raw is not None else default
    except (TypeError, ValueError):
        return default


def _is_marketplace(url: str) -> bool:
    u = (url or "").lower()
    return any(dom in u for dom in _MARKETPLACE_DOMAINS)


def _is_product_page(url: str, title: str) -> bool:
    """Drop only unambiguous search-results pages; keep everything else."""
    u = (url or "").lower()
    return not any(h in u for h in _SEARCH_URL_HINTS)


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    nums = re.findall(r"[\d.]+", str(value).replace(",", ""))
    try:
        return float(nums[0]) if nums else None
    except ValueError:
        return None


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


def _iter_jsonld(html: str):
    for blob in _JSONLD_RE.findall(html or ""):
        try:
            data = json.loads(blob.strip())
        except (ValueError, TypeError):
            continue
        if isinstance(data, list):
            yield from (d for d in data if isinstance(d, dict))
        elif isinstance(data, dict):
            # @graph wrapper is common
            graph = data.get("@graph")
            if isinstance(graph, list):
                yield from (d for d in graph if isinstance(d, dict))
            yield data


def _jsonld_product(html: str) -> dict:
    """Pull title/price/image/rating from a Product JSON-LD block, if present."""
    for node in _iter_jsonld(html):
        node_type = node.get("@type")
        types = node_type if isinstance(node_type, list) else [node_type]
        if not any(str(t).lower() == "product" for t in types):
            continue
        image = node.get("image")
        if isinstance(image, dict):
            image = image.get("url")
        if isinstance(image, list):
            image = next((i for i in image if i), None)
        offers = node.get("offers")
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        offers = offers if isinstance(offers, dict) else {}
        rating = node.get("aggregateRating")
        rating_val = rating.get("ratingValue") if isinstance(rating, dict) else None
        availability = str(offers.get("availability") or "").lower()
        return {
            "title": node.get("name"),
            "image_url": image,
            "price_inr": offers.get("price"),
            "rating": rating_val,
            "in_stock": ("instock" in availability) or ("/instock" in availability) or not availability,
            "description": (node.get("description") or "")[:200],
        }
    return {}


class MarketplaceSource:
    SOURCE_ID = SOURCE_ID

    def __init__(self, *, tavily=None, browserbase=None, provider=None, session=None):
        self._tavily = tavily
        self._browserbase = browserbase
        self._provider = provider
        self._session = session

    # --- lazy wiring (kept out of __init__ so import never needs creds) ---
    def _get_tavily(self):
        if self._tavily is None:
            from el import tavily as tavily_mod
            self._tavily = tavily_mod.default_provider()
        return self._tavily

    def _get_session(self):
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update(_BROWSER_HEADERS)
        return self._session

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

    def _fetch_html(self, url: str) -> str:
        """Fast direct fetch; Browserbase fallback only if blocked and enabled."""
        try:
            resp = self._get_session().get(url, timeout=_FETCH_TIMEOUT)
            if resp.status_code == 200 and resp.text:
                return resp.text
            blocked = resp.status_code in (403, 429, 503)
        except requests.RequestException:
            blocked = True
        if blocked and _flag("EL_MARKETPLACE_USE_BROWSERBASE", True):
            bb = self._get_browserbase()
            if bb is not None:
                fetched = bb.fetch(url)
                if fetched.get("ok") and fetched.get("content"):
                    return str(fetched["content"])
        return ""

    def _llm_extract(self, query: str, url: str, text: str) -> dict:
        if not text:
            return {}
        user = f"Trend/query: {query}\nMarketplace URL: {url}\n\nPAGE TEXT:\n{text[:8000]}"
        try:
            raw = self._get_provider().generate(_SYSTEM, user)
        except Exception as exc:
            log.warning("marketplace: extraction LLM call failed soft: %s", exc)
            return {}
        return _parse_obj(raw)

    def _extract(self, query: str, result: dict) -> SupplierCandidate | None:
        url = result.get("url", "")
        html = self._fetch_html(url)

        # 1) Structured JSON-LD Product — cleanest, no LLM needed.
        data = _jsonld_product(html) if html else {}

        # 2) Fill any gaps with an LLM pass over Tavily's clean snippet.
        if not data.get("title") or data.get("price_inr") in (None, ""):
            tavily_text = (result.get("raw_content") or result.get("content") or "").strip()
            llm_data = self._llm_extract(query, url, tavily_text)
            for k, v in llm_data.items():
                if data.get(k) in (None, "", []) and v not in (None, ""):
                    data[k] = v

        # 3) Image fallback: og:image meta tag.
        if not data.get("image_url") and html:
            m = _OG_IMAGE_RE.search(html)
            if m:
                data["image_url"] = m.group(1)

        title = str(data.get("title") or result.get("title") or "").strip()
        if not title:
            return None

        in_stock = data.get("in_stock", True)

        # Believable-economics simulation: the scraped price IS the retail price
        # the shopper pays. Keep it as the sell-side market reference and infer a
        # plausible wholesale cost + delivery window so Sentinel's margin/delivery
        # gates do real work (see module docstring + design spec).
        retail = _to_float(data.get("price_inr"))
        cost_factor = _float_config("EL_MARKETPLACE_COST_FACTOR", _DEFAULT_COST_FACTOR)
        cost = round(retail * cost_factor, 2) if retail is not None else None
        ship_min = _int_config("EL_MARKETPLACE_SHIP_DAYS_MIN", _DEFAULT_SHIP_DAYS_MIN)
        ship_max = _int_config("EL_MARKETPLACE_SHIP_DAYS_MAX", _DEFAULT_SHIP_DAYS_MAX)

        raw_payload: dict[str, Any] = {
            "marketplace": next((d for d in _MARKETPLACE_DOMAINS if d in url), ""),
            "description": str(data.get("description") or "").strip(),
            "source_url": url,
            "simulated_economics": True,
        }
        if retail is not None:
            # Real scraped retail → Sentinel uses this as the sell price (market basis).
            raw_payload["market_price"] = retail

        return SupplierCandidate(
            title=title,
            source_id=SOURCE_ID,
            product_url=url,
            image_url=(str(data["image_url"]).strip() if data.get("image_url") else None),
            cost=cost,
            currency="INR",
            shipping_cost=0.0,
            shipping_days_min=ship_min,
            shipping_days_max=ship_max,
            stock=1 if in_stock else 0,
            rating=_to_float(data.get("rating")),
            raw_payload=raw_payload,
        )

    def search_products(self, query: str, ctx: dict) -> list[SupplierCandidate]:
        if not query or not self._credentials_available():
            if not self._credentials_available():
                log.info("marketplace: EMPTY (no key) — TAVILY_API_KEY / GOOGLE_SERVICE_ACCOUNT_JSON not set")
            return []

        try:
            search = self._get_tavily().search(
                f"buy {query} online India price", max_results=10, include_raw_content=True,
            )
        except Exception as exc:
            log.warning("marketplace: tavily search failed soft: %s", exc)
            return []
        if not search.get("ok"):
            return []

        hits = [
            r for r in search.get("results", [])
            if _is_marketplace(r.get("url", "")) and _is_product_page(r.get("url", ""), r.get("title", ""))
        ]
        hits = hits[: _int_config("EL_MARKETPLACE_MAX_PAGES", _MAX_PAGES_PER_TREND)]

        candidates: list[SupplierCandidate] = []
        for result in hits:
            cand = self._extract(query, result)
            if cand is not None:
                candidates.append(cand)

        log.info(
            "marketplace: %s — %d listing(s) for %r (%d product hits)",
            "OK" if candidates else "EMPTY", len(candidates), query, len(hits),
        )
        return candidates


def default_source() -> MarketplaceSource:
    return MarketplaceSource()
