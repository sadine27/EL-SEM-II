"""HIL callback poller — daemon thread alongside the pipeline worker.

Long-polls Telegram getUpdates for callback_query updates (Approve/Reject taps).
Each batch runs through the callback pipeline:
  parse_hil_callback → apply_hil_callback → answer_hil_callback
  → if_callback_finalized_review → edit_hil_message + send_hil_fx (per item)
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
from el.nodes import send_hil_fx

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


def _upload_approved_to_shopify(_item: dict) -> None:
    """Best-effort: sync ALL approved products to Shopify after any approval.

    Clears the store first, then re-uploads every approved row from Supabase
    so the store always shows exactly the approved set with no garbage left over.
    Never blocks the callback flow; all exceptions are swallowed.
    """
    try:
        from el import shopify
        from el.supabase import HIL_REVIEWS_SCHEMA, HIL_REVIEWS_TABLE, SupabaseRestProvider
        from el.nodes.upload_shopify_products import _clear_existing_products, create_one

        if not config.get("SHOPIFY_STORE_DOMAIN"):
            return

        db = SupabaseRestProvider()
        approved_rows = db.select_rows(
            schema=HIL_REVIEWS_SCHEMA,
            table=HIL_REVIEWS_TABLE,
            filters={"approval_status": "eq.approved", "order": "reviewed_at.desc"},
            limit=100,
        )
        if not approved_rows:
            log.info("HIL poller: no approved products — clearing store")

        # Deduplicate by product_url, keep most-recently-approved copy
        seen: set[str] = set()
        unique: list[dict] = []
        for row in approved_rows:
            key = row.get("product_url") or row.get("product_name") or ""
            if key and key not in seen:
                seen.add(key)
                unique.append(row)

        provider = shopify.default_provider()
        _clear_existing_products(provider)

        ok = 0
        for row in unique:
            result = create_one(row, provider=provider)
            if result["ok"]:
                ok += 1
                log.info(
                    "HIL poller: uploaded %r (id=%s)",
                    result.get("pick_name"),
                    result.get("product_id"),
                )
            else:
                log.warning(
                    "HIL poller: upload failed for %r: %s",
                    result.get("pick_name"),
                    result.get("error"),
                )

        log.info("HIL poller: Shopify sync complete — %d/%d uploaded", ok, len(unique))
    except Exception:
        log.exception("HIL poller: Shopify sync failed — best-effort")


def _process_batch(updates: list[dict]) -> None:
    ctx: dict = {"telegram_updates": updates}
    parse_hil_callback.run(ctx)
    apply_hil_callback.run(ctx)
    answer_hil_callback.run(ctx)
    if_callback_finalized_review.run(ctx)
    for item in ctx.get("hil_finalized_callbacks") or []:
        edit_hil_message.run({"hil_finalized_callbacks": item})
        send_hil_fx.run({"hil_finalized_callbacks": item})
        if item.get("approval_status") == "approved":
            _upload_approved_to_shopify(item)


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

    # Sync approved products to Shopify on every startup so the store is
    # always correct after a Docker restart without needing a manual script.
    _upload_approved_to_shopify({})

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
