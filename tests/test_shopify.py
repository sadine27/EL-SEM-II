"""Tests for el/shopify.py — Admin REST client."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from el import shopify


class FakeResp:
    def __init__(self, status_code=200, json_data=None, text="", json_exc=None):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text
        self._json_exc = json_exc

    def json(self):
        if self._json_exc:
            raise self._json_exc
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


def test_get_theme_asset_uses_asset_key_param():
    prov = _provider()
    with patch("el.shopify.requests.request") as req:
        req.return_value = FakeResp(200, {"asset": {"key": "assets/tokens.css", "value": ":root {}"}})
        asset = prov.get_theme_asset(7, "assets/tokens.css")
    method, url = req.call_args.args
    assert method == "GET"
    assert url.endswith("/themes/7/assets.json")
    assert req.call_args.kwargs["params"] == {"asset[key]": "assets/tokens.css"}
    assert asset["value"] == ":root {}"


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


def test_delete_product_uses_delete_endpoint():
    prov = _provider()
    with patch("el.shopify.requests.request") as req:
        req.return_value = FakeResp(200, {})
        prov.delete_product(42)
    method, url = req.call_args.args
    assert method == "DELETE"
    assert url.endswith("/products/42.json")


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


def test_4xx_response_redacts_configured_token_from_shopify_error(monkeypatch):
    token = "plain-secret-token"
    prov = shopify.ShopifyRestProvider(
        domain="shop.myshopify.com",
        token=token,
        api_version="2024-10",
        sleep=lambda _: None,
    )

    def fake_request(*args, **kwargs):
        return FakeResp(401, text=f"unauthorized token={token}")

    monkeypatch.setattr(shopify.requests, "request", fake_request)

    with pytest.raises(shopify.ShopifyError) as exc:
        prov.list_themes()

    message = str(exc.value)
    assert token not in message
    assert "***REDACTED***" in message


def test_redact_masks_shopify_token_patterns_and_configured_client_secret(monkeypatch):
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "client-id")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "client-secret-value")
    prov = shopify.ShopifyRestProvider(
        domain="shop.myshopify.com",
        token=None,
        api_version="2024-10",
        sleep=lambda _: None,
    )

    redacted = prov._redact(
        "shpat_abc123 shpca_def456 client-secret-value visible"
    )

    assert "shpat_abc123" not in redacted
    assert "shpca_def456" not in redacted
    assert "client-secret-value" not in redacted
    assert redacted.count("***REDACTED***") == 3


def test_constructor_raises_without_admin_token_or_client_credentials(monkeypatch):
    monkeypatch.delenv("SHOPIFY_ADMIN_API_TOKEN", raising=False)
    monkeypatch.delenv("SHOPIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SHOPIFY_CLIENT_SECRET", raising=False)

    with pytest.raises(shopify.ShopifyError):
        shopify.ShopifyRestProvider(domain="shop.myshopify.com")


def test_admin_token_takes_priority_and_skips_oauth(monkeypatch):
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "client-id")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "client-secret")
    calls = []

    def fake_request(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResp(200, {"access_token": "oauth-token"})

    monkeypatch.setattr(shopify.requests, "request", fake_request)
    prov = _provider()

    assert prov._headers()["X-Shopify-Access-Token"] == "tok-x"
    assert calls == []


def test_client_credentials_posts_caches_and_headers_use_oauth_token(monkeypatch):
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "client-id")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(shopify.time, "time", lambda: 1000)
    calls = []

    def fake_request(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResp(200, {"access_token": "oauth-token", "expires_in": 3600})

    monkeypatch.setattr(shopify.requests, "request", fake_request)
    prov = shopify.ShopifyRestProvider(
        domain="shop.myshopify.com",
        token=None,
        api_version="2024-10",
        sleep=lambda _: None,
    )

    headers = prov._headers()
    cached_headers = prov._headers()

    assert headers["X-Shopify-Access-Token"] == "oauth-token"
    assert cached_headers["X-Shopify-Access-Token"] == "oauth-token"
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ("POST", "https://shop.myshopify.com/admin/oauth/access_token")
    assert kwargs["headers"] == {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    assert kwargs["json"] == {
        "grant_type": "client_credentials",
        "client_id": "client-id",
        "client_secret": "client-secret",
    }
    assert kwargs["timeout"] == shopify.DEFAULT_TIMEOUT


def test_cached_oauth_token_reused_before_expiry_skew(monkeypatch):
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "client-id")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "client-secret")
    now = 1000
    monkeypatch.setattr(shopify.time, "time", lambda: now)
    calls = []

    def fake_request(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResp(200, {"access_token": "oauth-token", "expires_in": 3600})

    monkeypatch.setattr(shopify.requests, "request", fake_request)
    prov = shopify.ShopifyRestProvider(
        domain="shop.myshopify.com",
        token=None,
        api_version="2024-10",
        sleep=lambda _: None,
    )

    assert prov._headers()["X-Shopify-Access-Token"] == "oauth-token"
    now = 4539
    assert prov._headers()["X-Shopify-Access-Token"] == "oauth-token"
    assert len(calls) == 1


def test_expired_oauth_token_triggers_refresh(monkeypatch):
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "client-id")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "client-secret")
    now = 1000
    monkeypatch.setattr(shopify.time, "time", lambda: now)
    tokens = ["first-token", "second-token"]
    calls = []

    def fake_request(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResp(200, {"access_token": tokens[len(calls) - 1], "expires_in": 120})

    monkeypatch.setattr(shopify.requests, "request", fake_request)
    prov = shopify.ShopifyRestProvider(
        domain="shop.myshopify.com",
        token=None,
        api_version="2024-10",
        sleep=lambda _: None,
    )

    assert prov._headers()["X-Shopify-Access-Token"] == "first-token"
    now = 1060
    assert prov._headers()["X-Shopify-Access-Token"] == "second-token"
    assert len(calls) == 2


@pytest.mark.parametrize(
    "response_or_exception",
    [
        FakeResp(400, text="bad request"),
        shopify.requests.RequestException("connection failed"),
        FakeResp(200, json_exc=ValueError("not json")),
        FakeResp(200, {"expires_in": 3600}),
    ],
)
def test_client_credentials_errors_raise_shopify_error(monkeypatch, response_or_exception):
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "client-id")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "client-secret")

    def fake_request(*args, **kwargs):
        if isinstance(response_or_exception, Exception):
            raise response_or_exception
        return response_or_exception

    monkeypatch.setattr(shopify.requests, "request", fake_request)
    prov = shopify.ShopifyRestProvider(
        domain="shop.myshopify.com",
        token=None,
        api_version="2024-10",
        sleep=lambda _: None,
    )

    with pytest.raises(shopify.ShopifyError):
        prov._headers()
