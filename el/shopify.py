"""SP5b — Shopify Admin REST API client (2024-10).

Single-operator MVP: one configured dev store via SHOPIFY_STORE_DOMAIN plus
either SHOPIFY_ADMIN_API_TOKEN or SHOPIFY_CLIENT_ID + SHOPIFY_CLIENT_SECRET.
No SDK; plain `requests`. Fail-soft retry on 429/5xx.
"""
from __future__ import annotations

import re
import time
from typing import Protocol

import requests

from el import config
from el.logger import get_logger

log = get_logger(__name__)

SHOPIFY_API_VERSION = "2024-10"
DEFAULT_TIMEOUT = 30
_RETRY_STATUS = {429, 500, 502, 503, 504}
TOKEN_EXPIRY_SKEW_SECONDS = 60
DEFAULT_CLIENT_CREDENTIALS_EXPIRES_IN = 24 * 60 * 60
SHOPIFY_SECRET_PATTERN = re.compile(r"shp(?:at|ca)_[A-Za-z0-9]+")


class ShopifyError(RuntimeError):
    pass


class ShopifyAdminProvider(Protocol):
    def list_themes(self) -> list[dict]: ...
    def get_main_theme_id(self) -> int | None: ...
    def get_theme_asset(self, theme_id: int, key: str) -> dict: ...
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
        self.token = token or config.get("SHOPIFY_ADMIN_API_TOKEN")
        self.client_id = config.get("SHOPIFY_CLIENT_ID")
        self.client_secret = config.get("SHOPIFY_CLIENT_SECRET")
        self.api_version = api_version or config.get("SHOPIFY_API_VERSION", SHOPIFY_API_VERSION)
        self.timeout = timeout
        self.max_retries = max_retries
        self._sleep = sleep
        self._cached_token: str | None = None
        self._token_expires_at = 0.0

        if not self.token and not (self.client_id and self.client_secret):
            raise ShopifyError(
                "missing Shopify auth: set SHOPIFY_ADMIN_API_TOKEN or "
                "SHOPIFY_CLIENT_ID + SHOPIFY_CLIENT_SECRET"
            )

    @property
    def base_url(self) -> str:
        return f"https://{self.domain}/admin/api/{self.api_version}"

    @property
    def oauth_url(self) -> str:
        return f"https://{self.domain}/admin/oauth/access_token"

    def _redact(self, text: str) -> str:
        redacted = SHOPIFY_SECRET_PATTERN.sub("***REDACTED***", text)
        for secret in (self.token, self.client_secret):
            if secret:
                redacted = redacted.replace(secret, "***REDACTED***")
        return redacted

    def _access_token(self) -> str:
        if self.token:
            return self.token

        now = time.time()
        if self._cached_token and now < (self._token_expires_at - TOKEN_EXPIRY_SKEW_SECONDS):
            return self._cached_token

        return self._fetch_client_credentials_token(now)

    def _fetch_client_credentials_token(self, now: float) -> str:
        if not self.client_id or not self.client_secret:
            raise ShopifyError(
                "missing Shopify client credentials: set SHOPIFY_CLIENT_ID and "
                "SHOPIFY_CLIENT_SECRET"
            )

        try:
            resp = requests.request(
                "POST",
                self.oauth_url,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ShopifyError(
                f"POST /admin/oauth/access_token network error: {self._redact(str(exc))}"
            ) from exc

        if resp.status_code >= 400:
            text = self._redact(resp.text)
            raise ShopifyError(
                f"POST /admin/oauth/access_token failed {resp.status_code}: {text[:300]}"
            )

        try:
            payload = resp.json()
        except ValueError as exc:
            raise ShopifyError("POST /admin/oauth/access_token returned invalid JSON") from exc

        access_token = payload.get("access_token")
        if not access_token:
            raise ShopifyError("POST /admin/oauth/access_token returned no access_token")

        expires_in = payload.get("expires_in") or DEFAULT_CLIENT_CREDENTIALS_EXPIRES_IN
        try:
            expires_in_seconds = int(expires_in)
        except (TypeError, ValueError):
            expires_in_seconds = DEFAULT_CLIENT_CREDENTIALS_EXPIRES_IN

        self._cached_token = str(access_token)
        self._token_expires_at = now + max(1, expires_in_seconds)
        return self._cached_token

    def _headers(self) -> dict:
        return {
            "X-Shopify-Access-Token": self._access_token(),
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
                    raise ShopifyError(
                        f"{method} {path} network error: {self._redact(str(exc))}"
                    ) from exc
                self._sleep(2 ** (attempt - 1))
                continue
            if resp.status_code in _RETRY_STATUS and attempt < self.max_retries:
                log.warning("shopify: %s %s -> %d (retry %d)", method, path, resp.status_code, attempt)
                self._sleep(2 ** (attempt - 1))
                continue
            if resp.status_code >= 400:
                text = self._redact(resp.text)
                raise ShopifyError(
                    f"{method} {path} failed {resp.status_code}: {text[:300]}"
                )
            return resp
        last_exc_text = self._redact(str(last_exc)) if last_exc else last_exc
        raise ShopifyError(f"{method} {path} exhausted retries: {last_exc_text}")

    def list_themes(self) -> list[dict]:
        resp = self._request("GET", "/themes.json")
        return resp.json().get("themes", []) or []

    def get_main_theme_id(self) -> int | None:
        for theme in self.list_themes():
            if theme.get("role") == "main":
                return int(theme["id"])
        return None

    def get_theme_asset(self, theme_id: int, key: str) -> dict:
        resp = self._request(
            "GET",
            f"/themes/{theme_id}/assets.json",
            params={"asset[key]": key},
        )
        return resp.json().get("asset", {}) or {}

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
