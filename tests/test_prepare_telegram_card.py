"""Tests for el/nodes/prepare_telegram_card.py."""
from __future__ import annotations

import json

import pytest

from el.nodes import prepare_telegram_card


def _row(**overrides) -> dict:
    row = {
        "id": 42,
        "callback_token": "123e4567-e89b-12d3-a456-426614174000",
        "product_name": "Wireless <Earbuds>",
        "price_text": "2.02 -- 14.10",
        "price_numeric": 2.02,
        "currency": "USD",
        "product_rating": None,
        "reviews_count": None,
        "marketplace": "cjdropshipping",
        "source_provider": "cj_dropshipping",
        "source_topic": "Wireless Earbuds",
        "product_url": "https://example.com/product",
        "image_url": " https://img.example/1.jpg ",
        "raw_payload": json.dumps({
            "phase4_selection": {"confidence_score": 82.5},
            "phase4_debug": {"score": 80},
        }),
    }
    row.update(overrides)
    return row


def test_money_prefers_price_text_then_formats_numeric():
    assert prepare_telegram_card.money(_row()) == "2.02 -- 14.10"
    assert prepare_telegram_card.money(_row(price_text="", currency="INR")) == "INR 2.02"
    assert prepare_telegram_card.money(_row(price_text="", price_numeric=None)) == "price n/a"


def test_rating_formats_known_and_unknown_values():
    assert prepare_telegram_card.rating(_row()) == "rating n/a"
    assert prepare_telegram_card.rating(_row(product_rating=4.5, reviews_count=1200)) == "4.5/5 (1200)"


def test_build_caption_escapes_html_and_includes_score():
    caption = prepare_telegram_card.build_caption(_row())

    assert "<b>Wireless &lt;Earbuds&gt;</b>" in caption
    assert "Price: <b>2.02 -- 14.10</b>" in caption
    assert "Score: <b>82.5</b>" in caption


def test_build_callback_rejects_payload_over_telegram_limit():
    with pytest.raises(ValueError, match="over 64 bytes"):
        prepare_telegram_card.build_callback(
            "a",
            _row(id="9" * 30),
        )


def test_build_card_maps_telegram_fields():
    card = prepare_telegram_card.build_card(_row(), chat_id="chat-1")

    assert card["review_id"] == 42
    assert card["telegram_chat_id"] == "chat-1"
    assert card["telegram_file_name"] == "hil-review-42.jpg"
    assert card["telegram_approve_callback"] == "a:42:123e4567-e89b-12d3-a456-426614174000"
    assert card["telegram_reject_callback"].startswith("r:42:")
    assert card["telegram_skip_callback"].startswith("s:42:")
    assert card["telegram_text"].endswith("Image unavailable: sending text card.")
    assert card["image_url"] == "https://img.example/1.jpg"


def test_run_stores_telegram_cards():
    ctx = prepare_telegram_card.run({"hil_review_rows": [_row()]}, chat_id="chat-1")

    assert len(ctx["telegram_cards"]) == 1
    assert ctx["telegram_cards"][0]["telegram_chat_id"] == "chat-1"
