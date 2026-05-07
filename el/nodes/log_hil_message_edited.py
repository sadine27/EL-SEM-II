"""Port of n8n node `Log HIL Message Edited`."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from el.logger import get_logger
from el.supabase import (
    HIL_REVIEW_EVENTS_TABLE,
    HIL_REVIEWS_SCHEMA,
    SupabaseRestProvider,
)

log = get_logger(__name__)


class HilMessageEditLogger(Protocol):
    def log_message_edited(self, review_id: int | str, edit_result: dict) -> dict | None:
        ...


class SupabaseHilMessageEditLogger:
    def __init__(self, provider: SupabaseRestProvider | None = None):
        self.provider = provider or SupabaseRestProvider()

    def log_message_edited(self, review_id: int | str, edit_result: dict) -> dict | None:
        event_row = {
            "review_id": int(review_id),
            "event_type": "message_edited",
            "actor_type": "workflow",
            "actor_id": "workflow",
            "payload": {
                "method": "editMessageText",
                "ok": edit_result.get("ok", False),
                "error": edit_result.get("error"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        rows = self.provider.insert_rows(
            schema=HIL_REVIEWS_SCHEMA,
            table=HIL_REVIEW_EVENTS_TABLE,
            rows=[event_row],
        )
        return rows[0] if rows else None


def run(ctx: dict, *, logger: HilMessageEditLogger | None = None) -> dict:
    callback_data = ctx.get("hil_finalized_callbacks") or {}
    if not isinstance(callback_data, dict):
        callback_data = {}
    review_id = callback_data.get("review_id")
    edit_result = ctx.get("edit_hil_message_result") or {}

    if not review_id:
        ctx["log_hil_message_edited_result"] = {
            "ok": False,
            "error": "Missing review_id",
        }
        log.warning("Log HIL Message Edited skipped: missing review_id")
        return ctx

    try:
        event_logger = logger or SupabaseHilMessageEditLogger()
    except Exception as exc:  # noqa: BLE001
        ctx["log_hil_message_edited_result"] = {
            "ok": False,
            "error": str(exc),
        }
        log.warning("Log HIL Message Edited skipped: %s", exc)
        return ctx

    try:
        event = event_logger.log_message_edited(review_id, edit_result)
        if event:
            ctx["hil_message_edited_event"] = event
            ctx["log_hil_message_edited_result"] = {"ok": True}
            log.info("Log HIL Message Edited: logged event for review %s", review_id)
        else:
            ctx["log_hil_message_edited_result"] = {
                "ok": False,
                "error": "Failed to insert event",
            }
            log.error("Log HIL Message Edited: failed to insert for review %s", review_id)
    except Exception as exc:  # noqa: BLE001
        ctx["log_hil_message_edited_result"] = {
            "ok": False,
            "error": str(exc),
        }
        log.error("Log HIL Message Edited failed: %s", exc)

    return ctx
