"""Format workflow error as Markdown message for Telegram alert."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def run(ctx: dict) -> dict:
    """Format error dict as Markdown for Telegram delivery.

    Input: ctx["workflow_error"] — n8n error object
    Output: ctx["formatted_error"] — single item with Markdown text field
    """
    formatted_error = []

    if not ctx.get("workflow_error"):
        ctx["formatted_error"] = formatted_error
        return ctx

    err = ctx["workflow_error"]

    # Extract node name from nested error structure
    node_name = (
        err.get("error", {}).get("node", {}).get("name")
        or err.get("error", {}).get("context", {}).get("nodeName")
        or err.get("node", {}).get("name")
        or err.get("context", {}).get("nodeName")
        or "Unknown Node"
    )

    # Extract error message — prefer error.message, then description, then JSON dump
    msg = (
        err.get("error", {}).get("message")
        or err.get("message")
        or err.get("error", {}).get("description")
        or str(err.get("error", err))
    )

    # Truncate to 300 chars
    msg = msg[:300]

    # Build IST timestamp
    ist_tz = ZoneInfo("Asia/Kolkata")
    ts = datetime.now(ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")

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
