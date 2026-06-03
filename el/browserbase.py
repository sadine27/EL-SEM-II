"""Browserbase API helper for marketplace content fetching."""
from __future__ import annotations

import requests

from el import config
from el.logger import get_logger

log = get_logger(__name__)


class BrowserbaseProvider:
    """Browserbase API — fetch full marketplace page content."""

    BASE_URL = "https://api.browserbase.com/v1/fetch"
    DEFAULT_TIMEOUT = 60

    def __init__(self, api_key: str | None = None, timeout: int = DEFAULT_TIMEOUT):
        self.api_key = api_key or config.require("BROWSERBASE_API_KEY")
        self.timeout = timeout

    def fetch(self, url: str, allow_redirects: bool = True, proxies: bool = True) -> dict:
        """Fetch URL content via Browserbase. Returns {content: str, statusCode: int, error?: str}."""
        try:
            headers = {
                "X-BB-API-Key": self.api_key,
                "Content-Type": "application/json",
            }
            body = {
                "url": url,
                "allowRedirects": allow_redirects,
                "proxies": proxies,
            }
            resp = requests.post(
                self.BASE_URL,
                json=body,
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "ok": True,
                "url": url,
                "content": data.get("content", ""),
                "statusCode": data.get("statusCode", 200),
            }
        except requests.exceptions.RequestException as e:
            log.warning(f"Browserbase fetch failed for {url}: {e}")
            return {
                "ok": False,
                "url": url,
                "statusCode": getattr(e.response, 'status_code', 0),
                "error": str(e),
            }
        except Exception as e:
            log.error(f"Browserbase fetch error for {url}: {e}")
            return {
                "ok": False,
                "url": url,
                "error": str(e),
            }
