"""Minimal Telegram Bot API client for HIL review delivery nodes."""
from __future__ import annotations

import json
from typing import Protocol

import requests

from el import config

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
DEFAULT_TIMEOUT = 20


class TelegramProvider(Protocol):
    def send_photo(
        self,
        *,
        chat_id: str,
        photo: dict,
        caption: str,
        file_name: str,
        reply_markup: dict,
    ) -> dict:
        ...

    def send_message(
        self,
        *,
        chat_id: str,
        text: str,
        reply_markup: dict,
        disable_web_page_preview: bool = False,
    ) -> dict:
        ...

    def answer_callback(
        self,
        *,
        callback_query_id: str,
        text: str,
        show_alert: bool = False,
        cache_time: int = 0,
    ) -> dict:
        ...

    def edit_message_text(
        self,
        *,
        chat_id: str,
        message_id: int,
        text: str,
        disable_web_page_preview: bool = False,
    ) -> dict:
        ...

    def delete_message(
        self,
        *,
        chat_id: str,
        message_id: int,
    ) -> dict:
        ...


class TelegramBotProvider:
    def __init__(self, token: str | None = None, timeout: int = DEFAULT_TIMEOUT):
        self.token = token or config.require("TELEGRAM_HIL_BOT_TOKEN")
        self.timeout = timeout

    def send_photo(
        self,
        *,
        chat_id: str,
        photo: dict,
        caption: str,
        file_name: str,
        reply_markup: dict,
    ) -> dict:
        data = photo.get("data")
        if not isinstance(data, bytes):
            raise ValueError("product_image.data must be bytes")
        resp = requests.post(
            TELEGRAM_API.format(token=self.token, method="sendPhoto"),
            data={
                "chat_id": chat_id,
                "caption": caption,
                "parse_mode": "HTML",
                "reply_markup": json.dumps(reply_markup, separators=(",", ":")),
            },
            files={
                "photo": (
                    file_name,
                    data,
                    str(photo.get("mimeType") or "application/octet-stream"),
                )
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("ok") is not True:
            raise RuntimeError(str(payload.get("description") or "Telegram sendPhoto failed"))
        return payload

    def send_message(
        self,
        *,
        chat_id: str,
        text: str,
        reply_markup: dict,
        disable_web_page_preview: bool = False,
    ) -> dict:
        resp = requests.post(
            TELEGRAM_API.format(token=self.token, method="sendMessage"),
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": reply_markup,
                "disable_web_page_preview": disable_web_page_preview,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("ok") is not True:
            raise RuntimeError(str(payload.get("description") or "Telegram sendMessage failed"))
        return payload

    def answer_callback(
        self,
        *,
        callback_query_id: str,
        text: str,
        show_alert: bool = False,
        cache_time: int = 0,
    ) -> dict:
        resp = requests.post(
            TELEGRAM_API.format(token=self.token, method="answerCallbackQuery"),
            json={
                "callback_query_id": callback_query_id,
                "text": text,
                "show_alert": show_alert,
                "cache_time": cache_time,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("ok") is not True:
            raise RuntimeError(str(payload.get("description") or "Telegram answerCallbackQuery failed"))
        return payload

    def edit_message_text(
        self,
        *,
        chat_id: str,
        message_id: int,
        text: str,
        disable_web_page_preview: bool = False,
    ) -> dict:
        resp = requests.post(
            TELEGRAM_API.format(token=self.token, method="editMessageText"),
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": disable_web_page_preview,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("ok") is not True:
            raise RuntimeError(str(payload.get("description") or "Telegram editMessageText failed"))
        return payload

    def delete_message(
        self,
        *,
        chat_id: str,
        message_id: int,
    ) -> dict:
        resp = requests.post(
            TELEGRAM_API.format(token=self.token, method="deleteMessage"),
            json={
                "chat_id": chat_id,
                "message_id": message_id,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("ok") is not True:
            raise RuntimeError(str(payload.get("description") or "Telegram deleteMessage failed"))
        return payload


def default_provider() -> TelegramProvider:
    return TelegramBotProvider()
