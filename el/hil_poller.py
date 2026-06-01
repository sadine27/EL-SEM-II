"""HIL callback poller — daemon thread alongside the pipeline worker.

Long-polls Telegram getUpdates for callback_query updates (Approve/Reject taps).
Each batch runs through the callback pipeline:
  parse_hil_callback → apply_hil_callback → answer_hil_callback
  → if_callback_finalized_review → edit_hil_message (per finalized item)
"""
from __future__ import annotations

import logging
import threading

import requests

from el import config
from el.telegram import TELEGRAM_API
from el.nodes import answer_hil_callback
from el.nodes import apply_hil_callback
from el.nodes import edit_hil_message
from el.nodes import if_callback_finalized_review
from el.nodes import parse_hil_callback

log = logging.getLogger("el.hil_poller")

_LONG_POLL_TIMEOUT = 25
_ERROR_SLEEP = 5


def _delete_webhook(token: str) -> None:
    resp = requests.post(
        TELEGRAM_API.format(token=token, method="deleteWebhook"),
        json={"drop_pending_updates": False},
        timeout=10,
    )
    resp.raise_for_status()
    log.info("HIL poller: webhook cleared")


def _get_updates(token: str, offset: int, timeout: int) -> list[dict]:
    resp = requests.post(
        TELEGRAM_API.format(token=token, method="getUpdates"),
        json={"offset": offset, "timeout": timeout, "allowed_updates": ["callback_query"]},
        timeout=timeout + 10,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("ok"):
        raise RuntimeError(f"getUpdates failed: {payload.get('description')}")
    return payload.get("result") or []


def _process_batch(updates: list[dict]) -> None:
    ctx: dict = {"telegram_updates": updates}
    parse_hil_callback.run(ctx)
    apply_hil_callback.run(ctx)
    answer_hil_callback.run(ctx)
    if_callback_finalized_review.run(ctx)
    for item in ctx.get("hil_finalized_callbacks") or []:
        edit_hil_message.run({"hil_finalized_callbacks": item})


def poll_loop(*, stop: threading.Event, token: str | None = None) -> None:
    try:
        bot_token = token or config.require("TELEGRAM_HIL_BOT_TOKEN")
    except Exception as exc:
        log.warning("HIL poller disabled (no token): %s", exc)
        return

    try:
        _delete_webhook(bot_token)
    except Exception:
        log.exception("HIL poller: failed to delete webhook — polling may fail with 409")

    offset = 0
    log.info("HIL poller starting (long-poll timeout=%ds)", _LONG_POLL_TIMEOUT)

    while not stop.is_set():
        try:
            updates = _get_updates(bot_token, offset, _LONG_POLL_TIMEOUT)
            if updates:
                log.info("HIL poller: %d update(s) received", len(updates))
                _process_batch(updates)
                offset = updates[-1]["update_id"] + 1
        except Exception:
            log.exception("HIL poller error — retrying in %ds", _ERROR_SLEEP)
            stop.wait(_ERROR_SLEEP)

    log.info("HIL poller stopped")
