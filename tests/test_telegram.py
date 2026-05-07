"""Tests for el/telegram.py."""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from el.telegram import TelegramBotProvider


def test_send_photo_posts_multipart_request_shape():
    response = Mock()
    response.json.return_value = {"ok": True, "result": {"message_id": 99}}
    response.raise_for_status.return_value = None

    with patch("el.telegram.requests.post", return_value=response) as mock_post:
        result = TelegramBotProvider(token="TKN").send_photo(
            chat_id="123",
            photo={"data": b"img", "mimeType": "image/jpeg"},
            caption="<b>Card</b>",
            file_name="hil-review-1.jpg",
            reply_markup={"inline_keyboard": [[{"text": "Approve", "callback_data": "a:1:t"}]]},
        )

    assert result["result"]["message_id"] == 99
    assert mock_post.call_args.args[0] == "https://api.telegram.org/botTKN/sendPhoto"
    assert mock_post.call_args.kwargs["data"]["chat_id"] == "123"
    assert mock_post.call_args.kwargs["data"]["parse_mode"] == "HTML"
    assert "reply_markup" in mock_post.call_args.kwargs["data"]
    assert mock_post.call_args.kwargs["files"]["photo"] == (
        "hil-review-1.jpg",
        b"img",
        "image/jpeg",
    )


def test_send_photo_rejects_non_bytes_image_data():
    with pytest.raises(ValueError, match="must be bytes"):
        TelegramBotProvider(token="TKN").send_photo(
            chat_id="123",
            photo={"data": "not-bytes"},
            caption="caption",
            file_name="x.jpg",
            reply_markup={"inline_keyboard": []},
        )


def test_send_photo_raises_on_telegram_error_payload():
    response = Mock()
    response.json.return_value = {"ok": False, "description": "bad request"}
    response.raise_for_status.return_value = None

    with patch("el.telegram.requests.post", return_value=response):
        with pytest.raises(RuntimeError, match="bad request"):
            TelegramBotProvider(token="TKN").send_photo(
                chat_id="123",
                photo={"data": b"img"},
                caption="caption",
                file_name="x.jpg",
                reply_markup={"inline_keyboard": []},
            )


def test_send_message_posts_json_request_shape():
    response = Mock()
    response.json.return_value = {"ok": True, "result": {"message_id": 100}}
    response.raise_for_status.return_value = None

    with patch("el.telegram.requests.post", return_value=response) as mock_post:
        result = TelegramBotProvider(token="TKN").send_message(
            chat_id="123",
            text="<b>Card</b>",
            reply_markup={"inline_keyboard": [[{"text": "Approve", "callback_data": "a:1:t"}]]},
            disable_web_page_preview=False,
        )

    assert result["result"]["message_id"] == 100
    assert mock_post.call_args.args[0] == "https://api.telegram.org/botTKN/sendMessage"
    payload = mock_post.call_args.kwargs["json"]
    assert payload["chat_id"] == "123"
    assert payload["text"] == "<b>Card</b>"
    assert payload["parse_mode"] == "HTML"
    assert payload["disable_web_page_preview"] is False
    assert payload["reply_markup"]["inline_keyboard"][0][0]["text"] == "Approve"


def test_send_message_raises_on_telegram_error_payload():
    response = Mock()
    response.json.return_value = {"ok": False, "description": "message is empty"}
    response.raise_for_status.return_value = None

    with patch("el.telegram.requests.post", return_value=response):
        with pytest.raises(RuntimeError, match="message is empty"):
            TelegramBotProvider(token="TKN").send_message(
                chat_id="123",
                text="",
                reply_markup={"inline_keyboard": []},
            )


def test_answer_callback_posts_json_request_shape():
    response = Mock()
    response.json.return_value = {"ok": True, "result": True}
    response.raise_for_status.return_value = None

    with patch("el.telegram.requests.post", return_value=response) as mock_post:
        result = TelegramBotProvider(token="TKN").answer_callback(
            callback_query_id="cb-1",
            text="Approved recorded.",
            show_alert=False,
            cache_time=0,
        )

    assert result == {"ok": True, "result": True}
    assert mock_post.call_args.args[0] == "https://api.telegram.org/botTKN/answerCallbackQuery"
    payload = mock_post.call_args.kwargs["json"]
    assert payload == {
        "callback_query_id": "cb-1",
        "text": "Approved recorded.",
        "show_alert": False,
        "cache_time": 0,
    }


def test_answer_callback_raises_on_telegram_error_payload():
    response = Mock()
    response.json.return_value = {"ok": False, "description": "query is too old"}
    response.raise_for_status.return_value = None

    with patch("el.telegram.requests.post", return_value=response):
        with pytest.raises(RuntimeError, match="query is too old"):
            TelegramBotProvider(token="TKN").answer_callback(
                callback_query_id="cb-1",
                text="Already reviewed.",
            )
