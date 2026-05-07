"""Tests for el/nodes/download_product_image.py."""
from __future__ import annotations

import pytest

from el.nodes import download_product_image


class FakeProvider:
    def __init__(self, failures: set[str] | None = None):
        self.failures = failures or set()
        self.calls = []

    def download(self, url: str, *, file_name: str) -> dict:
        self.calls.append({"url": url, "file_name": file_name})
        if url in self.failures:
            raise RuntimeError("download failed")
        return {
            "data": b"image-bytes",
            "mimeType": "image/jpeg",
            "fileName": file_name,
            "fileExtension": "jpg",
        }


def _card(**overrides) -> dict:
    card = {
        "review_id": 42,
        "image_url": "https://img.example/1.jpg",
        "telegram_file_name": "hil-review-42.jpg",
        "telegram_text": "fallback text",
    }
    card.update(overrides)
    return card


def test_mime_type_prefers_response_content_type():
    assert download_product_image._mime_type("image/webp; charset=binary", "x.jpg") == "image/webp"
    assert download_product_image._mime_type(None, "x.png") == "image/png"
    assert download_product_image._mime_type(None, "x.unknown") == "application/octet-stream"


@pytest.mark.parametrize(
    ("file_name", "mime_type", "expected"),
    [
        ("hil-review-42.jpg", "image/jpeg", "jpg"),
        ("hil-review-42", "image/png", "png"),
        ("https://example.com/a.webp", "image/jpeg", "webp"),
    ],
)
def test_file_extension_uses_name_then_mime_type(file_name, mime_type, expected):
    assert download_product_image._file_extension(file_name, mime_type) == expected


def test_run_routes_successful_downloads_to_photo_cards():
    provider = FakeProvider()
    ctx = download_product_image.run({"telegram_cards": [_card()]}, provider=provider)

    assert provider.calls == [{
        "url": "https://img.example/1.jpg",
        "file_name": "hil-review-42.jpg",
    }]
    assert len(ctx["telegram_photo_cards"]) == 1
    assert ctx["telegram_photo_cards"][0]["product_image"]["data"] == b"image-bytes"
    assert ctx["telegram_text_fallback_cards"] == []
    assert ctx["download_product_image_result"] == {
        "ok": True,
        "attempted": 1,
        "downloaded": 1,
        "fallback": 0,
    }


def test_run_routes_failed_downloads_to_text_fallback_cards():
    provider = FakeProvider(failures={"https://img.example/bad.jpg"})
    ctx = download_product_image.run(
        {"telegram_cards": [_card(image_url="https://img.example/bad.jpg")]},
        provider=provider,
    )

    assert ctx["telegram_photo_cards"] == []
    assert len(ctx["telegram_text_fallback_cards"]) == 1
    assert ctx["telegram_text_fallback_cards"][0]["image_download_error"] == "download failed"
    assert ctx["download_product_image_result"]["fallback"] == 1


def test_run_skips_non_dict_cards():
    provider = FakeProvider()
    ctx = download_product_image.run({"telegram_cards": [_card(), None, "bad"]}, provider=provider)

    assert len(ctx["telegram_photo_cards"]) == 1
    assert ctx["download_product_image_result"]["attempted"] == 1
