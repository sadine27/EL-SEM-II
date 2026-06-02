"""Forge supplier adapter for the existing CJ Dropshipping client."""
from __future__ import annotations

import re
from typing import Any, Callable

from el import cj, config
from el.logger import get_logger
from el.suppliers import SupplierCandidate

log = get_logger(__name__)

SOURCE_ID = "cj"


def _parse_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    nums = re.findall(r"[\d.]+", str(value))
    if not nums:
        return None
    try:
        return float(nums[0])
    except ValueError:
        return None


def _parse_int(value: object) -> int | None:
    parsed = _parse_float(value)
    return int(parsed) if parsed is not None else None


def _first_image(value: object) -> str | None:
    if isinstance(value, list):
        for item in value:
            if item:
                return str(item)
        return None
    images = [img.strip() for img in str(value or "").split(";") if img.strip()]
    return images[0] if images else None


def _token(response: object) -> str | None:
    if not isinstance(response, dict):
        return None
    if response.get("code") not in (None, 200, "200"):
        return None
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    token = data.get("accessToken")
    return str(token) if token else None


def _products(response: object) -> list[dict]:
    if not isinstance(response, dict):
        return []
    if response.get("code") not in (None, 200, "200"):
        return []
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    products = data.get("list") or []
    if not isinstance(products, list):
        return []
    return [product for product in products if isinstance(product, dict)]


def _product_url(product: dict) -> str | None:
    explicit = product.get("productUrl") or product.get("product_url")
    if explicit:
        return str(explicit)
    pid = product.get("pid") or product.get("productId")
    if not pid:
        return None
    return f"https://app.cjdropshipping.com/product/{pid}.html"


def _map_product(product: dict) -> SupplierCandidate | None:
    title = product.get("productNameEn") or product.get("productName") or product.get("title")
    if not title:
        return None

    shipping_cost = _parse_float(product.get("shippingCost") or product.get("freight"))
    if product.get("isFreeShipping") is True and shipping_cost is None:
        shipping_cost = 0.0

    return SupplierCandidate(
        title=str(title),
        source_id=SOURCE_ID,
        supplier_product_id=str(product.get("pid") or product.get("productId") or ""),
        product_url=_product_url(product),
        image_url=_first_image(product.get("productImage") or product.get("imageUrls")),
        cost=_parse_float(product.get("sellPrice") or product.get("price")),
        currency=str(product.get("currency") or "USD"),
        shipping_cost=shipping_cost,
        shipping_days_min=_parse_int(product.get("shippingDaysMin") or product.get("deliveryDaysMin")),
        shipping_days_max=_parse_int(product.get("shippingDaysMax") or product.get("deliveryDaysMax")),
        stock=_parse_int(product.get("stock") or product.get("listedNum")),
        moq=_parse_int(product.get("moq") or product.get("minOrderQuantity")),
        rating=_parse_float(product.get("rating") or product.get("productRating")),
        raw_payload=product,
    )


class CJSource:
    SOURCE_ID = SOURCE_ID

    def __init__(
        self,
        provider_factory: Callable[[], cj.CJProvider] | None = None,
        page_size: int = 20,
    ):
        self.provider_factory = provider_factory or cj.default_provider
        self.page_size = page_size

    def _credentials_available(self) -> bool:
        return bool(config.get("CJ_EMAIL") and config.get("CJ_API_KEY"))

    def search_products(self, query: str, ctx: dict) -> list[SupplierCandidate]:
        if not self._credentials_available():
            return []
        try:
            provider = self.provider_factory()
            token = _token(provider.get_access_token())
            if not token:
                return []
            response = provider.list_products(
                query,
                token,
                page_num=1,
                page_size=self.page_size,
            )
        except Exception as exc:
            log.warning("CJ supplier search failed soft: %s", exc)
            return []

        candidates = []
        for product in _products(response):
            candidate = _map_product(product)
            if candidate is not None:
                candidates.append(candidate)
        return candidates


def default_source() -> CJSource:
    return CJSource()
