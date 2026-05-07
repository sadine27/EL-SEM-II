"""Port of legacy/el_error_handler.json (Format Error Message + Alert Developer).

Wrap pipeline execution in `error_handler()` and any uncaught exception is
formatted and posted to the developer Telegram chat before the process exits.
"""
from __future__ import annotations

import traceback
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from typing import Iterator

import requests

from el import config
from el.logger import get_logger

log = get_logger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
MSG_TRUNCATE = 400


def format_error_message(node_name: str, exc: BaseException, ts: datetime) -> str:
    """Build the Telegram alert text. Mirrors the n8n Code node verbatim."""
    msg = str(exc) or exc.__class__.__name__
    msg = msg[:MSG_TRUNCATE]
    ts_str = ts.astimezone(IST).strftime("%d/%m/%Y, %I:%M:%S %p")
    return (
        "🚨 *EL Node Failed*\n\n"
        f"❌ *Node:* {node_name}\n"
        f"📋 *Error:* {msg}\n"
        f"🕐 *Time (IST):* {ts_str}\n"
        "🔗 _Local Python run — see stderr for traceback_"
    )


def send_telegram_alert(text: str) -> bool:
    """POST to Telegram. Returns True on success, False if creds missing or call failed."""
    token = config.get("EL_DEVELOPER_ALERT_TOKEN_KEY")
    chat_id = config.get("EL_DEVELOPER_ALERT_CHAT_ID")
    if not token or not chat_id:
        log.warning("Telegram alert skipped: EL_DEVELOPER_ALERT_TOKEN_KEY or _CHAT_ID not set")
        return False
    resp = requests.post(
        TELEGRAM_API.format(token=token),
        json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        timeout=10,
    )
    if not resp.ok:
        log.error("Telegram alert failed: %s %s", resp.status_code, resp.text[:200])
        return False
    return True


def _node_name_from_traceback(tb) -> str:
    """Extract the deepest frame's module name as the failing 'node'."""
    while tb.tb_next is not None:
        tb = tb.tb_next
    module = tb.tb_frame.f_globals.get("__name__", "unknown")
    return module.replace("el.nodes.", "")


@contextmanager
def error_handler() -> Iterator[None]:
    try:
        yield
    except BaseException as exc:
        node_name = _node_name_from_traceback(exc.__traceback__) if exc.__traceback__ else "unknown"
        ts = datetime.now(timezone.utc)
        text = format_error_message(node_name, exc, ts)
        log.error("Pipeline crashed in node=%s: %s", node_name, exc)
        traceback.print_exc()
        send_telegram_alert(text)
        raise
