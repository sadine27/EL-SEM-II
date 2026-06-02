"""Tests for el/suppliers/__init__.py supplier protocol + candidate type."""
from __future__ import annotations

import dataclasses

import pytest

from el.suppliers import SupplierCandidate, SupplierSource


def test_supplier_candidate_is_frozen():
    c = SupplierCandidate(title="Wireless earbuds", source_id="cj")
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.title = "modified"  # type: ignore[misc]


def test_supplier_candidate_default_fields():
    c = SupplierCandidate(title="Wireless earbuds", source_id="cj")
    assert c.supplier_product_id is None
    assert c.product_url is None
    assert c.image_url is None
    assert c.cost is None
    assert c.currency is None
    assert c.shipping_cost is None
    assert c.shipping_days_min is None
    assert c.shipping_days_max is None
    assert c.stock is None
    assert c.moq is None
    assert c.rating is None
    assert c.raw_payload == {}


def test_supplier_candidate_default_raw_payload_is_distinct_dict():
    a = SupplierCandidate(title="A", source_id="cj")
    b = SupplierCandidate(title="B", source_id="eprolo")
    assert a.raw_payload == {}
    assert b.raw_payload == {}
    assert a.raw_payload is not b.raw_payload


def test_supplier_candidate_equality_by_value():
    a = SupplierCandidate(title="Wireless earbuds", source_id="cj", raw_payload={"id": 1})
    b = SupplierCandidate(title="Wireless earbuds", source_id="cj", raw_payload={"id": 1})
    assert a == b


def test_supplier_source_protocol_runtime_check_recognizes_conforming_class():
    class GoodSource:
        SOURCE_ID = "good"

        def search_products(self, query, ctx):
            return []

    assert isinstance(GoodSource(), SupplierSource)


def test_supplier_source_protocol_runtime_check_rejects_missing_method():
    class BadSource:
        SOURCE_ID = "bad"

    assert not isinstance(BadSource(), SupplierSource)
