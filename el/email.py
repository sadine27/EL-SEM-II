"""SMTP email provider + MIME builders for SP5a outbound digest / per-product."""
from __future__ import annotations

import html
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Protocol

from el import config
from el.logger import get_logger

log = get_logger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
DEFAULT_TIMEOUT = 30
XLSX_MIME_MAIN = "application"
XLSX_MIME_SUB = "vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class SmtpProvider(Protocol):
    def send(self, msg: EmailMessage) -> str:
        ...


class GmailSmtpProvider:
    """Sends an EmailMessage via Gmail SMTP over SSL (one connection per send).

    Single-operator volume (~25 msg/day) makes pooling unnecessary.
    """

    def __init__(
        self,
        user: str | None = None,
        app_password: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.user = user or config.require("GMAIL_SMTP_USER")
        self.app_password = app_password or config.require("GMAIL_SMTP_APP_PASSWORD")
        self.timeout = timeout

    def send(self, msg: EmailMessage) -> str:
        if not msg.get("Message-ID"):
            msg["Message-ID"] = make_msgid(domain="el.local")
        if not msg.get("From"):
            from_name = config.get("GMAIL_SMTP_FROM_NAME", "EL Bot")
            msg["From"] = f"{from_name} <{self.user}>"
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=self.timeout, context=ctx) as s:
            s.login(self.user, self.app_password)
            s.send_message(msg)
        return msg["Message-ID"]


def _price_of(pick: dict) -> str:
    txt = (pick.get("price_text") or "").strip()
    if txt:
        return txt
    num = pick.get("price_numeric")
    cur = (pick.get("currency") or "").strip().upper()
    if num is None:
        return "price n/a"
    try:
        return f"{cur} {float(num):g}".strip()
    except (TypeError, ValueError):
        return "price n/a"


def _safe(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def build_digest_message(
    *,
    to: str,
    subject: str,
    narrative: str,
    picks: list[dict],
    xlsx_bytes: bytes | None = None,
    xlsx_filename: str = "curated-picks.xlsx",
) -> EmailMessage:
    """Build the end-of-run digest email: narrative + product table + optional XLSX."""
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject

    text_lines = [narrative, ""]
    for i, p in enumerate(picks, 1):
        name = p.get("product_name") or p.get("topic") or "(unnamed)"
        text_lines.append(f"{i}. {name} — {_price_of(p)}")
        src = p.get("source_url") or p.get("marketplace") or ""
        if src:
            text_lines.append(f"   {src}")
    text_body = "\n".join(text_lines)
    msg.set_content(text_body)

    rows = []
    for i, p in enumerate(picks, 1):
        name = p.get("product_name") or p.get("topic") or "(unnamed)"
        src = p.get("source_url") or ""
        link = f'<a href="{_safe(src)}">link</a>' if src else ""
        rows.append(
            f"<tr><td>{i}</td><td>{_safe(name)}</td>"
            f"<td>{_safe(_price_of(p))}</td><td>{link}</td></tr>"
        )
    html_body = (
        "<html><body>"
        f"<p>{_safe(narrative)}</p>"
        "<table border='1' cellpadding='4' cellspacing='0'>"
        "<thead><tr><th>#</th><th>Product</th><th>Price</th><th>Source</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        "</body></html>"
    )
    msg.add_alternative(html_body, subtype="html")

    if xlsx_bytes:
        msg.add_attachment(
            xlsx_bytes,
            maintype=XLSX_MIME_MAIN,
            subtype=XLSX_MIME_SUB,
            filename=xlsx_filename,
        )
    return msg


def build_product_detail_message(*, to: str, subject: str, pick: dict) -> EmailMessage:
    """One product per email — image, price, why-it-fits, source link."""
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject

    name = pick.get("product_name") or pick.get("topic") or "(unnamed)"
    price = _price_of(pick)
    source_url = pick.get("source_url") or ""
    image_url = pick.get("image_url") or ""
    why = pick.get("why_it_fits") or pick.get("reason") or ""
    notes = pick.get("reviewer_notes") or ""

    text_body = (
        f"{name}\n"
        f"Price: {price}\n"
        f"Source: {source_url}\n\n"
        f"Why it fits: {why}\n"
        f"Notes: {notes}\n"
    )
    msg.set_content(text_body)

    img_html = (
        f'<img src="{_safe(image_url)}" alt="" style="max-width:480px"/><br>'
        if image_url
        else ""
    )
    src_html = f'<p><a href="{_safe(source_url)}">View source</a></p>' if source_url else ""
    html_body = (
        "<html><body>"
        f"<h2>{_safe(name)}</h2>"
        f"{img_html}"
        f"<p><strong>Price:</strong> {_safe(price)}</p>"
        f"<p><strong>Why it fits:</strong> {_safe(why)}</p>"
        f"<p><strong>Notes:</strong> {_safe(notes)}</p>"
        f"{src_html}"
        "</body></html>"
    )
    msg.add_alternative(html_body, subtype="html")
    return msg


_SUMMARY_SYSTEM = (
    "You are a concise product analyst. Given a niche and a list of curated "
    "picks (name + price), write a single paragraph (~70 words, no markdown, "
    "no lists) summarizing what stood out and why these picks match the niche."
)


def _build_summary_user_prompt(niche: str, picks: list[dict]) -> str:
    lines = [f"Niche: {niche or '(unspecified)'}", "Picks:"]
    for p in picks[:10]:
        name = p.get("product_name") or p.get("topic") or "(unnamed)"
        lines.append(f"- {name} — {_price_of(p)}")
    return "\n".join(lines)


def _deterministic_fallback(niche: str, picks: list[dict]) -> str:
    n = len(picks)
    if n == 0:
        return f"No picks were curated for the {niche or 'requested'} niche this run."
    prices = []
    for p in picks:
        v = p.get("price_numeric")
        try:
            prices.append(float(v))
        except (TypeError, ValueError):
            continue
    if prices:
        return (
            f"Top {n} picks for {niche or 'this niche'}, ranging "
            f"${min(prices):g}–${max(prices):g}."
        )
    return f"Top {n} picks for {niche or 'this niche'}."


def summarize_with_gemini(
    niche: str,
    picks: list[dict],
    *,
    provider=None,
) -> str:
    """~70-word narrative via Vertex Gemini. Falls back to deterministic string on failure."""
    if not picks:
        return _deterministic_fallback(niche, picks)
    try:
        if provider is None:
            from el import llm
            provider = llm.default_provider()
        text = provider.generate(_SUMMARY_SYSTEM, _build_summary_user_prompt(niche, picks))
        text = (text or "").strip()
        return text or _deterministic_fallback(niche, picks)
    except Exception as exc:
        log.warning("summarize_with_gemini: falling back (%s)", exc)
        return _deterministic_fallback(niche, picks)


def default_provider() -> SmtpProvider:
    return GmailSmtpProvider()
