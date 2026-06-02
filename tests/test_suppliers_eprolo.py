"""Tests for the fake-tested EPROLO supplier adapter."""
from __future__ import annotations

import requests

from el.nodes import supplier_search
from el.suppliers import SupplierCandidate
from el.suppliers.eprolo_source import EproloSource


class FakeResponse:
    def __init__(self, payload, status_code=200, json_error=None):
        self.payload = payload
        self.status_code = status_code
        self.json_error = json_error

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response or FakeResponse({"data": {"products": []}})
        self.error = error
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


def test_missing_credentials_returns_empty_and_does_not_call_http():
    session = FakeSession()
    source = EproloSource(api_key="", base_url="", session=session)

    assert source.search_products("wireless earbuds", {}) == []
    assert session.calls == []


def test_missing_base_url_returns_empty_and_does_not_call_http():
    session = FakeSession()
    source = EproloSource(api_key="KEY", base_url="", session=session)

    assert source.search_products("wireless earbuds", {}) == []
    assert session.calls == []


def test_non_200_http_error_returns_empty():
    session = FakeSession(response=FakeResponse({"data": {"products": []}}, status_code=500))
    source = EproloSource(api_key="KEY", base_url="https://api.eprolo.test", session=session)

    assert source.search_products("wireless earbuds", {}) == []


def test_api_error_returns_empty():
    session = FakeSession(response=FakeResponse({"code": 500, "data": {"products": []}}))
    source = EproloSource(api_key="KEY", base_url="https://api.eprolo.test", session=session)

    assert source.search_products("wireless earbuds", {}) == []


def test_malformed_json_returns_empty():
    session = FakeSession(response=FakeResponse(None, json_error=ValueError("bad json")))
    source = EproloSource(api_key="KEY", base_url="https://api.eprolo.test", session=session)

    assert source.search_products("wireless earbuds", {}) == []


def test_http_exception_returns_empty():
    session = FakeSession(error=requests.ConnectionError("down"))
    source = EproloSource(api_key="KEY", base_url="https://api.eprolo.test", session=session)

    assert source.search_products("wireless earbuds", {}) == []


def test_happy_path_maps_fake_response_shape_into_supplier_candidate():
    item = {
        "id": "EP123",
        "title": "Wireless Earbuds Pro",
        "url": "https://eprolo.test/products/ep123",
        "images": ["https://eprolo.test/ep123.jpg"],
        "cost": 11.25,
        "currency": "USD",
        "shipping": {"cost": 3.75, "days_min": 6, "days_max": 10},
        "stock": 80,
        "moq": 1,
        "rating": 4.6,
    }
    session = FakeSession(response=FakeResponse({"code": 200, "data": {"products": [item]}}))
    source = EproloSource(api_key="KEY", base_url="https://api.eprolo.test", session=session)

    out = source.search_products("wireless earbuds", {})

    assert len(out) == 1
    candidate = out[0]
    assert isinstance(candidate, SupplierCandidate)
    assert candidate.title == "Wireless Earbuds Pro"
    assert candidate.source_id == "eprolo"
    assert candidate.supplier_product_id == "EP123"
    assert candidate.product_url == "https://eprolo.test/products/ep123"
    assert candidate.image_url == "https://eprolo.test/ep123.jpg"
    assert candidate.cost == 11.25
    assert candidate.currency == "USD"
    assert candidate.shipping_cost == 3.75
    assert candidate.shipping_days_min == 6
    assert candidate.shipping_days_max == 10
    assert candidate.stock == 80
    assert candidate.moq == 1
    assert candidate.rating == 4.6
    assert candidate.raw_payload == item
    url, kwargs = session.calls[0]
    assert url == "https://api.eprolo.test/products/search"
    assert kwargs["headers"] == {"Authorization": "Bearer KEY"}
    assert kwargs["params"] == {"q": "wireless earbuds", "limit": 20}


def test_scoring_ranking_prefers_available_lower_landed_cost_faster_matches():
    session = FakeSession(response=FakeResponse({"data": {"products": [
        {
            "id": "SLOW",
            "title": "Wireless Earbuds",
            "cost": 75,
            "shipping_cost": 15,
            "shipping_days_min": 30,
            "stock": 0,
        },
        {
            "id": "FAST",
            "title": "Wireless Earbuds Pro",
            "image_url": "https://eprolo.test/fast.jpg",
            "cost": 10,
            "shipping_cost": 2,
            "shipping_days_min": 5,
            "stock": 60,
        },
    ]}}))
    source = EproloSource(api_key="KEY", base_url="https://api.eprolo.test", session=session)
    ctx = {"ranked_payload": {"trends": [{"topic": "wireless earbuds"}]}}

    out = supplier_search.run(ctx, sources=[source])

    matches = out["supplier_matches"][0]["matches"]
    assert matches[0]["supplier_product_id"] == "FAST"
    assert matches[0]["match_score"] > matches[1]["match_score"]
