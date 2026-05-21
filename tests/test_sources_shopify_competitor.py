"""Tests for el/sources/shopify_competitor.py."""
from __future__ import annotations

import json

import pytest
import requests

from el.sources import TrendCandidate
from el.sources import shopify_competitor as src


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, *, raise_json: bool = False):
        self.status_code = status_code
        self._payload = payload
        self._raise_json = raise_json
        self.text = "" if payload is None else json.dumps(payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if self._raise_json:
            raise ValueError("not json")
        return self._payload


def _product(idx: int, store: str = "examplestore") -> dict:
    return {
        "id": 1000 + idx,
        "title": f"Product {idx} from {store}",
        "handle": f"product-{idx}",
        "vendor": store,
        "published_at": "2026-05-20T10:00:00Z",
        "variants": [{"price": "19.99"}],
    }


def test_source_id():
    assert src.SOURCE_ID == "shopify_competitor"


def test_empty_stores_env_returns_empty(monkeypatch):
    monkeypatch.setenv("EL_SHOPIFY_COMPETITOR_STORES", "")
    called = []
    monkeypatch.setattr("requests.get", lambda *a, **kw: called.append(a) or _FakeResponse(200, {"products": []}))
    assert src.fetch_trends({}) == []
    assert called == []


def test_single_store_single_page(monkeypatch):
    monkeypatch.setenv("EL_SHOPIFY_COMPETITOR_STORES", "https://examplestore.com")
    monkeypatch.setenv("EL_SHOPIFY_COMPETITOR_MAX_PAGES", "4")

    def fake_get(url, params=None, timeout=None):
        page = params.get("page", 1) if params else 1
        if page == 1:
            return _FakeResponse(200, {"products": [_product(i) for i in range(3)]})
        return _FakeResponse(200, {"products": []})

    monkeypatch.setattr("requests.get", fake_get)
    candidates = src.fetch_trends({})
    assert len(candidates) == 3
    for c in candidates:
        assert isinstance(c, TrendCandidate)
        assert c.source_id == "shopify_competitor:examplestore"
        assert c.title.startswith("Product")


def test_pagination_stops_on_empty_page(monkeypatch):
    monkeypatch.setenv("EL_SHOPIFY_COMPETITOR_STORES", "https://examplestore.com")
    monkeypatch.setenv("EL_SHOPIFY_COMPETITOR_MAX_PAGES", "4")
    call_log = []

    def fake_get(url, params=None, timeout=None):
        page = params["page"]
        call_log.append(page)
        if page == 1:
            return _FakeResponse(200, {"products": [_product(i) for i in range(250)]})
        return _FakeResponse(200, {"products": []})

    monkeypatch.setattr("requests.get", fake_get)
    candidates = src.fetch_trends({})
    assert len(candidates) == 250
    # Page 1 returned full 250 (so we tried page 2), page 2 was empty → stop.
    assert call_log == [1, 2]


def test_max_pages_caps_pagination(monkeypatch):
    monkeypatch.setenv("EL_SHOPIFY_COMPETITOR_STORES", "https://examplestore.com")
    monkeypatch.setenv("EL_SHOPIFY_COMPETITOR_MAX_PAGES", "2")
    call_log = []

    def fake_get(url, params=None, timeout=None):
        call_log.append(params["page"])
        return _FakeResponse(200, {"products": [_product(i) for i in range(250)]})

    monkeypatch.setattr("requests.get", fake_get)
    candidates = src.fetch_trends({})
    assert len(candidates) == 500
    assert call_log == [1, 2]  # max-pages cap honored


def test_per_store_isolation_404(monkeypatch):
    monkeypatch.setenv(
        "EL_SHOPIFY_COMPETITOR_STORES",
        "https://broken.com,https://working.com",
    )

    def fake_get(url, params=None, timeout=None):
        if "broken" in url:
            return _FakeResponse(404)
        return _FakeResponse(200, {"products": [_product(0, store="working")]})

    monkeypatch.setattr("requests.get", fake_get)
    candidates = src.fetch_trends({})
    assert len(candidates) == 1
    assert candidates[0].source_id == "shopify_competitor:working"


def test_per_store_isolation_json_decode_error(monkeypatch):
    monkeypatch.setenv(
        "EL_SHOPIFY_COMPETITOR_STORES",
        "https://bad-json.com,https://good.com",
    )

    def fake_get(url, params=None, timeout=None):
        if "bad-json" in url:
            return _FakeResponse(200, payload=None, raise_json=True)
        return _FakeResponse(200, {"products": [_product(0, store="good")]})

    monkeypatch.setattr("requests.get", fake_get)
    candidates = src.fetch_trends({})
    assert len(candidates) == 1
    assert candidates[0].source_id == "shopify_competitor:good"


def test_per_store_isolation_timeout(monkeypatch):
    monkeypatch.setenv(
        "EL_SHOPIFY_COMPETITOR_STORES",
        "https://slow.com,https://fast.com",
    )

    def fake_get(url, params=None, timeout=None):
        if "slow" in url:
            raise requests.Timeout("timed out")
        return _FakeResponse(200, {"products": [_product(0, store="fast")]})

    monkeypatch.setattr("requests.get", fake_get)
    candidates = src.fetch_trends({})
    assert len(candidates) == 1
    assert candidates[0].source_id == "shopify_competitor:fast"


def test_url_with_trailing_slash_normalized(monkeypatch):
    monkeypatch.setenv("EL_SHOPIFY_COMPETITOR_STORES", "https://shop.com/")
    captured_urls = []

    def fake_get(url, params=None, timeout=None):
        captured_urls.append(url)
        return _FakeResponse(200, {"products": []})

    monkeypatch.setattr("requests.get", fake_get)
    src.fetch_trends({})
    assert captured_urls and captured_urls[0] == "https://shop.com/products.json"


def test_skips_products_without_title(monkeypatch):
    monkeypatch.setenv("EL_SHOPIFY_COMPETITOR_STORES", "https://shop.com")

    def fake_get(url, params=None, timeout=None):
        if params["page"] == 1:
            return _FakeResponse(200, {"products": [
                {"id": 1, "handle": "no-title"},  # missing title → skip
                _product(2, store="shop"),
            ]})
        return _FakeResponse(200, {"products": []})

    monkeypatch.setattr("requests.get", fake_get)
    candidates = src.fetch_trends({})
    assert len(candidates) == 1
    assert "Product 2" in candidates[0].title
