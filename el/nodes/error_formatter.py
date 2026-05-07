"""Format workflow error as Markdown message for Telegram alert."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# IST is a fixed offset (UTC+5:30, no DST). Using a fixed offset avoids
# depending on the IANA tz database, which is not bundled with Python on
# Windows and would otherwise require the `tzdata` package.
IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def _safe_dict(obj: object) -> dict:
    """Return obj if it's a dict, else an empty dict (None-safe)."""
    return obj if isinstance(obj, dict) else {}


def run(ctx: dict) -> dict:
    """Format error dict as Markdown for Telegram delivery.

    Input: ctx["workflow_error"] — n8n error object
    Output: ctx["formatted_error"] — single item with Markdown text field
    """
    formatted_error: list[dict] = []

    raw = ctx.get("workflow_error")
    if not raw:
        ctx["formatted_error"] = formatted_error
        return ctx

    err = _safe_dict(raw)
    inner = _safe_dict(err.get("error"))

    node_name = (
        _safe_dict(inner.get("node")).get("name")
        or _safe_dict(inner.get("context")).get("nodeName")
        or _safe_dict(err.get("node")).get("name")
        or _safe_dict(err.get("context")).get("nodeName")
        or "Unknown Node"
    )

    msg = (
        inner.get("message")
        or err.get("message")
        or inner.get("description")
        or str(err.get("error", err))
    )
    msg = str(msg)[:300]

    ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    # Build Markdown text
    text = (
        f"⚠️ *EL Node Failed*\n\n"
        f"🔴 *Node:* `{node_name}`\n"
        f"⚡ *Error:* {msg}\n"
        f"🕐 *Time (IST):* {ts}\n"
    )

    error_item = {"text": text}
    formatted_error.append(error_item)
    ctx["formatted_error"] = formatted_error

    return ctx
