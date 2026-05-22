"""SP5a — end-of-run digest email to the business owner."""
from __future__ import annotations

from typing import Any

from el import config, email as el_email
from el.google_drive import XLSX_MIME_TYPE
from el.logger import get_logger

log = get_logger(__name__)


def _picks_for_digest(ctx: dict) -> list[dict]:
    """Prefer product-level HIL rows (with prices/images); fall back to topic-level picks."""
    rows = ctx.get("hil_review_rows") or []
    if isinstance(rows, list) and rows:
        return [r for r in rows if isinstance(r, dict)]
    picks = ctx.get("curated_picks") or []
    return [p for p in picks if isinstance(p, dict) and "error" not in p]


def _xlsx_bytes_or_none(
    ctx: dict, *, drive_provider: Any, llm_provider: Any
) -> tuple[bytes | None, str | None]:
    sheet_id = ctx.get("sheet_id") or config.get("EL_DIGEST_SHEET_ID")
    if not sheet_id or drive_provider is None:
        return None, None
    try:
        data = drive_provider.export_file(sheet_id, XLSX_MIME_TYPE)
        return data, "xlsx_ok"
    except Exception as exc:
        log.warning("email_digest: xlsx export failed (%s) — sending without attachment", exc)
        return None, f"xlsx_export_failed: {exc}"


def _resolve_recipient(ctx: dict) -> str | None:
    return (
        ctx.get("business_email")
        or config.get("BUSINESS_NOTIFY_EMAIL")
        or config.get("GMAIL_SMTP_USER")
    )


def run(
    ctx: dict,
    *,
    provider: el_email.SmtpProvider | None = None,
    drive_provider=None,
    llm_provider=None,
) -> dict:
    picks = _picks_for_digest(ctx)
    to = _resolve_recipient(ctx)

    if not to:
        ctx["email_digest_result"] = {"ok": False, "error": "no recipient configured"}
        log.warning("email_digest: no recipient — skipping")
        return ctx
    if not picks:
        ctx["email_digest_result"] = {"ok": True, "to": to, "skipped": "no picks"}
        log.info("email_digest: no picks — skipping send")
        return ctx

    niche = ctx.get("niche") or ""
    request_id = ctx.get("request_id") or ctx.get("run_request_id") or ""
    subject = f"EL Run {request_id}: {len(picks)} picks for {niche or 'today'}".strip()

    narrative = el_email.summarize_with_gemini(niche, picks, provider=llm_provider)
    xlsx, xlsx_status = _xlsx_bytes_or_none(
        ctx, drive_provider=drive_provider, llm_provider=llm_provider,
    )

    msg = el_email.build_digest_message(
        to=to, subject=subject, narrative=narrative, picks=picks, xlsx_bytes=xlsx,
    )

    try:
        if provider is None:
            provider = el_email.default_provider()
        message_id = provider.send(msg)
    except Exception as exc:
        ctx["email_digest_result"] = {"ok": False, "to": to, "error": str(exc)}
        ctx.setdefault("formatted_error", []).append(
            {"text": f"email_digest failed: {exc}"}
        )
        log.exception("email_digest: send failed")
        return ctx

    ctx["email_digest_result"] = {
        "ok": True,
        "to": to,
        "message_id": message_id,
        "pick_count": len(picks),
        "xlsx": xlsx_status,
    }
    log.info("email_digest: sent to %s (%d picks)", to, len(picks))
    return ctx
