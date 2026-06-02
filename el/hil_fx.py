"""Presentation FX for the HIL Telegram review loop.

Pure helpers (text + feature flags, no I/O) that turn the plain Approve/Reject
feedback into something demo-ready:

  * a punchy confirmation toast (or modal popup) on the tapped button,
  * a quick two-frame "recording -> done" card animation, and
  * an optional celebratory "ding" message — a lone, big animated emoji whose
    arrival also fires Telegram's notification sound.

Everything here is additive and gated on ``EL_HIL_FX_ENABLED`` (default on).
With FX off, callers fall back to the original plain copy, so production
behaviour is unchanged unless you opt in. The source of truth — the Supabase
status write in ``apply_hil_callback`` — never depends on any of this; FX is
pure garnish and every FX side effect is best-effort.
"""
from __future__ import annotations

import html
from datetime import datetime

from el import config

# Statuses that earn the spicy treatment (the finalizing actions).
KNOWN_STATUSES = ("approved", "rejected", "skipped")

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


def _flag(name: str, *, default: bool) -> bool:
    raw = str(config.get(name, "true" if default else "false")).strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    return default


def fx_enabled() -> bool:
    """Master switch for all HIL presentation FX."""
    return _flag("EL_HIL_FX_ENABLED", default=True)


def alert_enabled() -> bool:
    """Confirm via a modal popup (``show_alert``) instead of a top toast.

    The toast is smoother; the popup is more visible on a projector at the back
    of a room. Default: toast.
    """
    return _flag("EL_HIL_FX_ALERT", default=False)


def ding_enabled() -> bool:
    """Send the celebratory animated-emoji "ding" after a decision is recorded."""
    return _flag("EL_HIL_FX_DING", default=True)


def buffer_seconds() -> float:
    """How long the "recording..." frame lingers before the final card."""
    try:
        ms = float(str(config.get("EL_HIL_FX_BUFFER_MS", "400")).strip())
    except (TypeError, ValueError):
        ms = 400.0
    return max(0.0, ms) / 1000.0


_TOAST = {
    "approved": "✅ Approved! Queuing it for the store \U0001f6d2",
    "rejected": "❌ Rejected — skipping this one",
    "skipped": "⏭️ Skipped for now",
}

# Lone emoji => Telegram renders it large; a new message fires the "ding".
_DING = {
    "approved": "\U0001f389",  # tada
    "rejected": "\U0001f44e",  # thumbs down
    "skipped": "⏭️",  # next track
}

_HEADLINE = {
    "approved": "✅ <b>APPROVED</b>",
    "rejected": "❌ <b>REJECTED</b>",
    "skipped": "⏭️ <b>SKIPPED</b>",
}

_TAGLINE = {
    "approved": "\U0001f6d2 Queued for the store",
    "rejected": "\U0001f5d1️ Won’t be listed",
    "skipped": "\U0001f4a4 Parked for later",
}

_BUFFER_LABEL = {
    "approved": "Approving",
    "rejected": "Rejecting",
    "skipped": "Skipping",
}


def toast_text(status: str) -> str:
    """Plain-text confirmation for answerCallbackQuery (no HTML allowed there)."""
    return _TOAST.get(status, "Recorded ✅")


def ding_emoji(status: str) -> str | None:
    """The lone emoji sent as the celebratory ding, or None for unknown status."""
    return _DING.get(status)


def buffer_text(status: str) -> str:
    """The brief "it's working" frame shown before the final card (HTML)."""
    label = _BUFFER_LABEL.get(status, "Recording")
    return f"⏳ <b>{label}…</b>\n<code>▰▰▰▱▱</code>"


def _fmt_time(value: object) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    return dt.strftime("%H:%M")


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def final_text(
    status: str,
    *,
    review_id: object = None,
    reviewed_by: object = None,
    reviewed_at: object = None,
    product_name: object = None,
) -> str:
    """The polished final card (HTML) shown once a decision is recorded."""
    headline = _HEADLINE.get(status, f"<b>{html.escape(status.title())}</b>")
    lines = [headline]

    name = _clean(product_name)
    if name:
        lines.append(f"\U0001f516 {html.escape(name[:80])}")

    tagline = _TAGLINE.get(status)
    if tagline:
        lines.append(tagline)

    who = _clean(reviewed_by) or "telegram_user"
    meta = f"\U0001f464 {html.escape(who)}"
    when = _fmt_time(reviewed_at)
    if when:
        meta += f"  ·  \U0001f552 {when}"
    if review_id not in (None, "", "0", 0):
        meta += f"  ·  #{html.escape(str(review_id))}"
    lines.append(meta)

    return "\n".join(lines)
