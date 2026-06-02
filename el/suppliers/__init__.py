"""Supplier-source protocol and shared Forge candidate type."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class SupplierCandidate:
    title: str
    source_id: str
    supplier_product_id: str | None = None
    product_url: str | None = None
    image_url: str | None = None
    cost: float | None = None
    currency: str | None = None
    shipping_cost: float | None = None
    shipping_days_min: int | None = None
    shipping_days_max: int | None = None
    stock: int | None = None
    moq: int | None = None
    rating: float | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SupplierSource(Protocol):
    SOURCE_ID: str

    def search_products(self, query: str, ctx: dict) -> list[SupplierCandidate]: ...
