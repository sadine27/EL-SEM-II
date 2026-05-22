"""SP5b — Shopify Admin REST API client (2024-10).

Single-operator MVP: one configured dev store via SHOPIFY_STORE_DOMAIN +
SHOPIFY_ADMIN_API_TOKEN. No SDK; plain `requests`. Fail-soft retry on 429/5xx.
"""
from __future__ import annotations

import time
from typing import Protocol

import requests

from el import config
from el.logger import get_logger

log = get_logger(__name__)

SHOPIFY_API_VERSION = "2024-10"
DEFAULT_TIMEOUT = 30
_RETRY_STATUS = {429, 500, 502, 503, 504}


class ShopifyError(RuntimeError):
    pass


class ShopifyAdminProvider(Protocol):
    def list_themes(self) -> list[dict]: ...
    def get_main_theme_id(self) -> int | None: ...
    def update_theme_asset(self, theme_id: int, key: str, value: str) -> dict: ...
    def create_product(
        self, payload: dict, *, idempotency_key: str | None = None
    ) -> dict: ...
    def find_product_by_handle(self, handle: str) -> dict | None: ...


class ShopifyRestProvider:
    def __init__(
        self,
        *,
        domain: str | None = None,
        token: str | None = None,
        api_version: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = 3,
        sleep=time.sleep,
    ):
        self.domain = (domain or config.require("SHOPIFY_STORE_DOMAIN")).strip().rstrip("/")
        self.token = token or config.require("SHOPIFY_ADMIN_API_TOKEN")
        self.api_version = api_version or config.get("SHOPIFY_API_VERSION", SHOPIFY_API_VERSION)
        self.timeout = timeout
        self.max_retries = max_retries
        self._sleep = sleep

    @property
    def base_url(self) -> str:
        return f"https://{self.domain}/admin/api/{self.api_version}"

    def _headers(self) -> dict:
        return {
            "X-Shopify-Access-Token": self.token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, *, json_body=None, params=None) -> requests.Response:
        url = f"{self.base_url}{path}"
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.request(
                    method, url,
                    headers=self._headers(),
                    json=json_body,
                    params=params,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_exc = exc
                if attempt == self.max_retries:
                    raise ShopifyError(f"{method} {path} network error: {exc}") from exc
                self._sleep(2 ** (attempt - 1))
                continue
            if resp.status_code in _RETRY_STATUS and attempt < self.max_retries:
                log.warning("shopify: %s %s -> %d (retry %d)", method, path, resp.status_code, attempt)
                self._sleep(2 ** (attempt - 1))
                continue
            if resp.status_code >= 400:
                raise ShopifyError(
                    f"{method} {path} failed {resp.status_code}: {resp.text[:300]}"
                )
            return resp
        raise ShopifyError(f"{method} {path} exhausted retries: {last_exc}")

    def list_themes(self) -> list[dict]:
        resp = self._request("GET", "/themes.json")
        return resp.json().get("themes", []) or []

    def get_main_theme_id(self) -> int | None:
        for theme in self.list_themes():
            if theme.get("role") == "main":
                return int(theme["id"])
        return None

    def update_theme_asset(self, theme_id: int, key: str, value: str) -> dict:
        body = {"asset": {"key": key, "value": value}}
        resp = self._request("PUT", f"/themes/{theme_id}/assets.json", json_body=body)
        return resp.json().get("asset", {}) or {}

    def find_product_by_handle(self, handle: str) -> dict | None:
        resp = self._request("GET", "/products.json", params={"handle": handle, "limit": 1})
        products = resp.json().get("products", []) or []
        return products[0] if products else None

    def create_product(
        self, payload: dict, *, idempotency_key: str | None = None
    ) -> dict:
        if idempotency_key:
            existing = self.find_product_by_handle(idempotency_key)
            if existing is not None:
                log.info("shopify: reusing existing product handle=%s id=%s",
                         idempotency_key, existing.get("id"))
                return existing
            payload = {
                **payload,
                "product": {**payload.get("product", {}), "handle": idempotency_key},
            }
        resp = self._request("POST", "/products.json", json_body=payload)
        return resp.json().get("product", {}) or {}


def default_provider() -> ShopifyAdminProvider:
    return ShopifyRestProvider()
