"""CJ Dropshipping API client for product discovery nodes."""
from __future__ import annotations

from typing import Protocol

import requests

from el import config

CJ_TOKEN_URL = "https://developers.cjdropshipping.com/api2.0/v1/authentication/getAccessToken"
CJ_PRODUCT_LIST_URL = "https://developers.cjdropshipping.com/api2.0/v1/product/list"
DEFAULT_TIMEOUT = 30


class CJProvider(Protocol):
    def get_access_token(self) -> dict:
        ...

    def list_products(
        self,
        keyword: str,
        access_token: str,
        page_num: int = 1,
        page_size: int = 20,
    ) -> dict:
        ...


class CJDropshippingProvider:
    def __init__(
        self,
        email: str | None = None,
        api_key: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.email = email or config.require("CJ_EMAIL")
        self.api_key = api_key or config.require("CJ_API_KEY")
        self.timeout = timeout

    def get_access_token(self) -> dict:
        resp = requests.post(
            CJ_TOKEN_URL,
            json={"email": self.email, "apiKey": self.api_key},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def list_products(
        self,
        keyword: str,
        access_token: str,
        page_num: int = 1,
        page_size: int = 20,
    ) -> dict:
        resp = requests.get(
            CJ_PRODUCT_LIST_URL,
            headers={"CJ-Access-Token": access_token},
            params={"pageNum": page_num, "pageSize": page_size, "keyWord": keyword},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()


def default_provider() -> CJProvider:
    return CJDropshippingProvider()
