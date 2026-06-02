"""Forge supplier adapter for EPROLO.

EPROLO API docs are not available in this handoff. This adapter is deliberately
credential-gated and maps a fake-tested response shape until real docs arrive.
"""
from __future__ import annotations

from typing import Any

import requests

from el import config
from el.logger import get_logger
from el.suppliers import SupplierCandidate

log = get_logger(__name__)

SOURCE_ID = "eprolo"
DEFAULT_TIMEOUT = 20


def _float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: object) -> int | None:
    parsed = _float(value)
    return int(parsed) if parsed is not None else None


def _first(value: object) -> str | None:
    if isinstance(value, list):
        for item in value:
            if item:
                return str(item)
        return None
    return str(value) if value else None


def _items(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    if payload.get("code") not in (None, 200, "200") or payload.get("ok") is False:
        return []
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    products = data.get("products") or data.get("items") or []
    if not isinstance(products, list):
        return []
    return [item for item in products if isinstance(item, dict)]


def _map_item(item: dict[str, Any]) -> SupplierCandidate | None:
    title = item.get("title") or item.get("name") or item.get("product_name")
    if not title:
        return None

    shipping = item.get("shipping") if isinstance(item.get("shipping"), dict) else {}
    return SupplierCandidate(
        title=str(title),
        source_id=SOURCE_ID,
        supplier_product_id=str(item.get("id") or item.get("product_id") or ""),
        product_url=_first(item.get("url") or item.get("product_url")),
        image_url=_first(item.get("image_url") or item.get("images")),
        cost=_float(item.get("cost") or item.get("price")),
        currency=str(item.get("currency") or "USD"),
        shipping_cost=_float(shipping.get("cost") or item.get("shipping_cost")),
        shipping_days_min=_int(shipping.get("days_min") or item.get("shipping_days_min")),
        shipping_days_max=_int(shipping.get("days_max") or item.get("shipping_days_max")),
        stock=_int(item.get("stock") or item.get("inventory")),
        moq=_int(item.get("moq")),
        rating=_float(item.get("rating")),
        raw_payload=item,
    )


class EproloSource:
    SOURCE_ID = SOURCE_ID

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        session=None,
    ):
        self.api_key = api_key if api_key is not None else config.get("EPROLO_API_KEY")
        self.base_url = base_url if base_url is not None else config.get("EPROLO_API_BASE_URL")
        self.timeout = timeout
        self.session = session or requests

    def _endpoint(self) -> str | None:
        if not self.api_key or not self.base_url:
            return None
        return f"{self.base_url.rstrip('/')}/products/search"

    def search_products(self, query: str, ctx: dict) -> list[SupplierCandidate]:
        endpoint = self._endpoint()
        if not endpoint:
            return []

        try:
            response = self.session.get(
                endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                params={"q": query, "limit": 20},
                timeout=self.timeout,
            )
            if getattr(response, "status_code", 200) != 200:
                return []
            payload = response.json()
        except Exception as exc:
            log.warning("EPROLO supplier search failed soft: %s", exc)
            return []

        candidates: list[SupplierCandidate] = []
        for item in _items(payload):
            candidate = _map_item(item)
            if candidate is not None:
                candidates.append(candidate)
        return candidates


def default_source() -> EproloSource:
    return EproloSource()
