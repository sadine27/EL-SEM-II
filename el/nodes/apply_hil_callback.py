"""Port of n8n node `Apply HIL Callback`."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from el.logger import get_logger
from el.supabase import (
    HIL_REVIEW_EVENTS_TABLE,
    HIL_REVIEWS_SCHEMA,
    HIL_REVIEWS_TABLE,
    SupabaseRestProvider,
)

log = get_logger(__name__)

ACTION_TO_STATUS = {
    "a": "approved",
    "r": "rejected",
    "s": "skipped",
}


class HilCallbackStore(Protocol):
    def find_review(self, review_id: int | str, callback_token: str) -> dict | None:
        ...

    def update_pending_review(
        self,
        review_id: int | str,
        callback_token: str,
        updates: dict,
    ) -> dict | None:
        ...

    def insert_event(self, row: dict) -> dict | None:
        ...


class SupabaseHilCallbackStore:
    def __init__(self, provider: SupabaseRestProvider | None = None):
        self.provider = provider or SupabaseRestProvider()

    def find_review(self, review_id: int | str, callback_token: str) -> dict | None:
        rows = self.provider.select_rows(
            schema=HIL_REVIEWS_SCHEMA,
            table=HIL_REVIEWS_TABLE,
            filters={
                "id": f"eq.{review_id}",
                "callback_token": f"eq.{callback_token}",
            },
            limit=1,
        )
        return rows[0] if rows else None

    def update_pending_review(
        self,
        review_id: int | str,
        callback_token: str,
        updates: dict,
    ) -> dict | None:
        rows = self.provider.update_rows(
            schema=HIL_REVIEWS_SCHEMA,
            table=HIL_REVIEWS_TABLE,
            filters={
                "id": f"eq.{review_id}",
                "callback_token": f"eq.{callback_token}",
                "approval_status": "eq.pending",
            },
            updates=updates,
        )
        return rows[0] if rows else None

    def insert_event(self, row: dict) -> dict | None:
        rows = self.provider.insert_rows(
            schema=HIL_REVIEWS_SCHEMA,
            table=HIL_REVIEW_EVENTS_TABLE,
            rows=[row],
        )
        return rows[0] if rows else None


def _now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()


def _reviewed_by(callback: dict) -> str:
    return (
        str(callback.get("actor_label") or "").strip()
        or str(callback.get("actor_id") or "").strip()
        or "telegram_user"
    )


def _to_int_or_none(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _title_status(status: str) -> str:
    return status[:1].upper() + status[1:]


def apply_callback(callback: dict, store: HilCallbackStore, *, now: datetime | None = None) -> dict:
    action_code = str(callback.get("action_code") or "")
    target_status = ACTION_TO_STATUS.get(action_code)
    review_id = callback.get("review_id") or "0"
    callback_token = str(callback.get("callback_token") or "")
    ts = _now_iso(now)

    matched = store.find_review(review_id, callback_token)
    updated = None

    if matched and target_status:
        updated = store.update_pending_review(
            review_id,
            callback_token,
            {
                "approval_status": target_status,
                "reviewed_by": _reviewed_by(callback),
                "reviewed_at": ts,
                "updated_at": ts,
            },
        )

        store.insert_event({
            "review_id": matched.get("id"),
            "event_type": "callback_received",
            "actor_type": "telegram_user",
            "actor_id": callback.get("actor_id") or None,
            "payload": {
                "action_code": action_code,
                "target_status": target_status,
                "callback_query_id": callback.get("callback_query_id"),
                "chat_id": _to_int_or_none(callback.get("chat_id")),
                "message_id": _to_int_or_none(callback.get("message_id")),
                "callback_data": callback.get("callback_data"),
                "was_pending": matched.get("approval_status") == "pending",
            },
        })

    if updated:
        store.insert_event({
            "review_id": updated.get("id"),
            "event_type": updated.get("approval_status"),
            "actor_type": "telegram_user",
            "actor_id": callback.get("actor_id") or None,
            "payload": {
                "callback_query_id": callback.get("callback_query_id"),
                "chat_id": _to_int_or_none(callback.get("chat_id")),
                "message_id": _to_int_or_none(callback.get("message_id")),
                "reviewed_by": updated.get("reviewed_by"),
                "reviewed_at": updated.get("reviewed_at"),
            },
        })

    row = updated or matched or {}
    approval_status = row.get("approval_status") or "invalid"
    reviewed_by = row.get("reviewed_by") or _reviewed_by(callback)
    reviewed_at = row.get("reviewed_at") or ts

    if target_status is None:
        answer = "Invalid review action."
    elif updated:
        answer = f"{_title_status(str(updated.get('approval_status')))} recorded."
    elif matched:
        answer = f"Already reviewed: {matched.get('approval_status')}."
    else:
        answer = "Review token is invalid or expired."

    return {
        "review_id": row.get("id") or review_id,
        "callback_query_id": callback.get("callback_query_id"),
        "chat_id": callback.get("chat_id"),
        "message_id": callback.get("message_id"),
        "approval_status": approval_status,
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at,
        "message_should_finalize": updated is not None,
        "callback_answer_text": answer,
        "telegram_edit_text": (
            f"<b>Review {updated.get('approval_status')}</b>"
            f"\nID: <code>{updated.get('id')}</code>"
            f"\nBy: {updated.get('reviewed_by') or 'telegram_user'}"
        )
        if updated
        else None,
    }


def run(ctx: dict, *, store: HilCallbackStore | None = None) -> dict:
    callbacks = [item for item in (ctx.get("hil_callbacks") or []) if isinstance(item, dict)]
    callback_store = store or SupabaseHilCallbackStore()
    results = []
    errors = []

    for callback in callbacks:
        try:
            results.append(apply_callback(callback, callback_store))
        except Exception as exc:  # noqa: BLE001 - n8n routes node errors to Error Formatter.
            errors.append({**callback, "apply_hil_callback_error": str(exc)})

    ctx["hil_callback_results"] = results
    ctx["apply_hil_callback_errors"] = errors
    ctx["apply_hil_callback_result"] = {
        "ok": not errors,
        "attempted": len(callbacks),
        "applied": len(results),
        "errors": len(errors),
    }
    log.info("Apply HIL Callback: applied %d/%d callbacks", len(results), len(callbacks))
    return ctx
