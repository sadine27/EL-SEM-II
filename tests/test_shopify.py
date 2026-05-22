"""Tests for el/shopify.py — Admin REST client."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from el import shopify


class FakeResp:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


def _provider(**kwargs):
    return shopify.ShopifyRestProvider(
        domain="shop.myshopify.com",
        token="tok-x",
        api_version="2024-10",
        sleep=lambda _: None,
        **kwargs,
    )


def test_list_themes_returns_array():
    prov = _provider()
    with patch("el.shopify.requests.request") as req:
        req.return_value = FakeResp(200, {"themes": [{"id": 1, "role": "main"}, {"id": 2, "role": "unpublished"}]})
        themes = prov.list_themes()
    assert len(themes) == 2
    assert themes[0]["id"] == 1


def test_get_main_theme_id():
    prov = _provider()
    with patch("el.shopify.requests.request") as req:
        req.return_value = FakeResp(200, {"themes": [{"id": 9, "role": "main"}]})
        assert prov.get_main_theme_id() == 9


def test_update_theme_asset_puts_payload():
    prov = _provider()
    with patch("el.shopify.requests.request") as req:
        req.return_value = FakeResp(200, {"asset": {"key": "snippets/x.liquid", "value": "<p>"}})
        asset = prov.update_theme_asset(7, "snippets/x.liquid", "<p>")
    method, url = req.call_args.args
    assert method == "PUT"
    assert url.endswith("/themes/7/assets.json")
    assert req.call_args.kwargs["json"] == {"asset": {"key": "snippets/x.liquid", "value": "<p>"}}
    assert asset["key"] == "snippets/x.liquid"


def test_create_product_posts_payload():
    prov = _provider()
    with patch("el.shopify.requests.request") as req:
        req.side_effect = [
            FakeResp(200, {"products": []}),  # find_product_by_handle: not found
            FakeResp(201, {"product": {"id": 42, "handle": "run-buds"}}),
        ]
        result = prov.create_product({"product": {"title": "Buds"}}, idempotency_key="run-buds")
    assert result["id"] == 42
    # second call is POST
    second_call = req.call_args_list[1]
    assert second_call.args[0] == "POST"
    assert second_call.kwargs["json"]["product"]["handle"] == "run-buds"


def test_create_product_reuses_existing_handle():
    prov = _provider()
    with patch("el.shopify.requests.request") as req:
        req.return_value = FakeResp(200, {"products": [{"id": 99, "handle": "run-buds"}]})
        result = prov.create_product({"product": {"title": "Buds"}}, idempotency_key="run-buds")
    assert result["id"] == 99
    assert req.call_count == 1  # no POST


def test_retry_on_429_then_success():
    prov = _provider(max_retries=3)
    with patch("el.shopify.requests.request") as req:
        req.side_effect = [
            FakeResp(429, text="rate"),
            FakeResp(200, {"themes": []}),
        ]
        themes = prov.list_themes()
    assert themes == []
    assert req.call_count == 2


def test_4xx_raises_shopify_error():
    prov = _provider()
    with patch("el.shopify.requests.request") as req:
        req.return_value = FakeResp(404, text="not found")
        with pytest.raises(shopify.ShopifyError):
            prov.list_themes()
