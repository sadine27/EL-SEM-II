"""SP5a — short Telegram ping to the business owner at end of run."""
from __future__ import annotations

from el import config
from el.telegram import TelegramProvider, TelegramBotProvider
from el.logger import get_logger

log = get_logger(__name__)

DEFAULT_CHAT_BASE_URL = "https://el.local/chat"


def _pick_count(ctx: dict) -> int:
    rows = ctx.get("hil_review_rows") or []
    if isinstance(rows, list) and rows:
        return len([r for r in rows if isinstance(r, dict)])
    picks = ctx.get("curated_picks") or []
    return len([p for p in picks if isinstance(p, dict) and "error" not in p])


def run(ctx: dict, *, provider: TelegramProvider | None = None) -> dict:
    chat_id = config.get("BUSINESS_NOTIFY_TELEGRAM_CHAT_ID") or config.get(
        "TELEGRAM_ALERT_CHAT_ID", "8243518279",
    )
    base_url = config.get("CHAT_BASE_URL", DEFAULT_CHAT_BASE_URL).rstrip("/")
    request_id = ctx.get("request_id") or ctx.get("run_request_id") or "(no-request-id)"
    niche = ctx.get("niche") or "today's batch"
    n = _pick_count(ctx)

    text = (
        f"Run `{request_id}` done — {n} picks for {niche}.\n"
        f"Chat: {base_url}/{request_id}"
    )

    try:
        if provider is None:
            provider = TelegramBotProvider()
        result = provider.send_message(
            chat_id=chat_id, text=text, reply_markup={}, parse_mode="Markdown",
        )
        ctx["notify_business_result"] = {"ok": True, "chat_id": chat_id, "result": result}
    except Exception as exc:
        ctx["notify_business_result"] = {"ok": False, "error": str(exc)}
        ctx.setdefault("formatted_error", []).append(
            {"text": f"notify_business failed: {exc}"}
        )
        log.exception("notify_business: send failed")

    return ctx
