"""Celebratory "ding" for finalized HIL decisions (presentation FX).

After a review is finalized, optionally drop a single big animated emoji into the
chat. A brand-new message fires Telegram's notification sound (the "ding") and a
lone supported emoji renders large + animated — a satisfying beat for a live
demo. Gated on ``EL_HIL_FX_ENABLED`` + ``EL_HIL_FX_DING`` and entirely
best-effort: it never blocks, retries, or fails the callback flow.
"""
from __future__ import annotations

from el import hil_fx as fx
from el.logger import get_logger
from el.telegram import TelegramProvider, default_provider

log = get_logger(__name__)


def run(ctx: dict, *, provider: TelegramProvider | None = None) -> dict:
    item = ctx.get("hil_finalized_callbacks") or {}
    if not isinstance(item, dict):
        item = {}
    status = str(item.get("approval_status") or "")
    chat_id = item.get("chat_id")
    emoji = fx.ding_emoji(status)

    if not (fx.fx_enabled() and fx.ding_enabled()):
        ctx["send_hil_fx_result"] = {"ok": True, "skipped": "disabled"}
        return ctx
    if not chat_id or not emoji or status not in fx.KNOWN_STATUSES:
        ctx["send_hil_fx_result"] = {"ok": True, "skipped": "no-target"}
        return ctx

    try:
        sender = provider or default_provider()
        sender.send_message(chat_id=str(chat_id), text=emoji, reply_markup={})
        ctx["send_hil_fx_result"] = {"ok": True, "sent": emoji}
        log.info("Send HIL FX: dinged %s for chat %s", status, chat_id)
    except Exception as exc:  # noqa: BLE001 - garnish only; failure must not propagate
        ctx["send_hil_fx_result"] = {"ok": False, "error": str(exc)}
        log.debug("Send HIL FX skipped: %s", exc)
    return ctx
