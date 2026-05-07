"""Port of n8n node `Download Product Image`."""
from __future__ import annotations

import mimetypes
from typing import Protocol
from urllib.parse import urlparse

import requests

from el.logger import get_logger

log = get_logger(__name__)

DEFAULT_TIMEOUT = 15
MAX_REDIRECTS = 5
IMAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; EL-HIL-Bot/1.0)",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
}


class ImageDownloadProvider(Protocol):
    def download(self, url: str, *, file_name: str) -> dict:
        ...


class RequestsImageDownloadProvider:
    def __init__(self, timeout: int = DEFAULT_TIMEOUT, max_redirects: int = MAX_REDIRECTS):
        self.timeout = timeout
        self.max_redirects = max_redirects

    def download(self, url: str, *, file_name: str) -> dict:
        if not url:
            raise ValueError("image_url is empty")

        session = requests.Session()
        session.max_redirects = self.max_redirects
        resp = session.get(
            url,
            headers=IMAGE_HEADERS,
            timeout=self.timeout,
            allow_redirects=True,
        )
        resp.raise_for_status()
        mime_type = _mime_type(resp.headers.get("Content-Type"), file_name)
        return {
            "data": resp.content,
            "mimeType": mime_type,
            "fileName": file_name,
            "fileExtension": _file_extension(file_name, mime_type),
        }


def _mime_type(content_type: str | None, file_name: str) -> str:
    if content_type:
        return content_type.split(";", 1)[0].strip() or "application/octet-stream"
    guessed, _ = mimetypes.guess_type(file_name)
    return guessed or "application/octet-stream"


def _file_extension(file_name: str, mime_type: str) -> str:
    suffix = ""
    path = urlparse(file_name).path
    if "." in path.rsplit("/", 1)[-1]:
        suffix = path.rsplit(".", 1)[-1]
    if suffix:
        return suffix.lower()
    guessed = mimetypes.guess_extension(mime_type) or ""
    return guessed.lstrip(".").lower()


def default_provider() -> ImageDownloadProvider:
    return RequestsImageDownloadProvider()


def run(ctx: dict, *, provider: ImageDownloadProvider | None = None) -> dict:
    cards = [card for card in (ctx.get("telegram_cards") or []) if isinstance(card, dict)]
    downloader = provider or default_provider()
    photo_cards = []
    fallback_cards = []

    for card in cards:
        try:
            product_image = downloader.download(
                str(card.get("image_url") or "").strip(),
                file_name=str(card.get("telegram_file_name") or "hil-review-item.jpg"),
            )
        except Exception as exc:  # noqa: BLE001 - n8n routes all node errors to fallback.
            fallback_cards.append({**card, "image_download_error": str(exc)})
            continue

        photo_cards.append({**card, "product_image": product_image})

    ctx["telegram_photo_cards"] = photo_cards
    ctx["telegram_text_fallback_cards"] = fallback_cards
    ctx["download_product_image_result"] = {
        "ok": True,
        "attempted": len(cards),
        "downloaded": len(photo_cards),
        "fallback": len(fallback_cards),
    }
    log.info(
        "Download Product Image: downloaded %d/%d cards, fallback %d",
        len(photo_cards),
        len(cards),
        len(fallback_cards),
    )
    return ctx
