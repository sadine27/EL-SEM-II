"""SP5a — per-product detail emails (one per approved pick)."""
from __future__ import annotations

from el import config, email as el_email
from el.logger import get_logger

log = get_logger(__name__)


def _picks(ctx: dict) -> list[dict]:
    rows = ctx.get("hil_review_rows") or []
    if isinstance(rows, list) and rows:
        return [r for r in rows if isinstance(r, dict)]
    picks = ctx.get("curated_picks") or []
    return [p for p in picks if isinstance(p, dict) and "error" not in p]


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
) -> dict:
    picks = _picks(ctx)
    to = _resolve_recipient(ctx)

    if not to:
        ctx["email_product_detail_results"] = []
        ctx.setdefault("formatted_error", []).append(
            {"text": "email_product_detail: no recipient configured"}
        )
        return ctx
    if not picks:
        ctx["email_product_detail_results"] = []
        return ctx

    if provider is None:
        try:
            provider = el_email.default_provider()
        except Exception as exc:
            ctx["email_product_detail_results"] = []
            ctx.setdefault("formatted_error", []).append(
                {"text": f"email_product_detail: provider init failed: {exc}"}
            )
            return ctx

    results: list[dict] = []
    for pick in picks:
        name = pick.get("product_name") or pick.get("topic") or "pick"
        subject = f"EL Pick: {name}"
        msg = el_email.build_product_detail_message(to=to, subject=subject, pick=pick)
        try:
            message_id = provider.send(msg)
            results.append({"ok": True, "pick_name": name, "message_id": message_id})
        except Exception as exc:
            log.warning("email_product_detail: send failed for %r: %s", name, exc)
            results.append({"ok": False, "pick_name": name, "error": str(exc)})

    ctx["email_product_detail_results"] = results
    failed = [r for r in results if not r["ok"]]
    if failed:
        ctx.setdefault("formatted_error", []).append(
            {"text": f"email_product_detail: {len(failed)}/{len(results)} sends failed"}
        )
    log.info(
        "email_product_detail: %d/%d sent to %s",
        len(results) - len(failed), len(results), to,
    )
    return ctx
