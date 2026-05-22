"""Tests for el/email.py pure builders + Gemini fallback."""
from __future__ import annotations

from email.message import EmailMessage

from el import email as el_email


def _walk_parts(msg: EmailMessage):
    return list(msg.walk())


def test_build_digest_message_has_text_html_no_attachment():
    msg = el_email.build_digest_message(
        to="x@y.com",
        subject="hello",
        narrative="A short narrative.",
        picks=[{"product_name": "P1", "price_text": "$10", "source_url": "https://e.com/p1"}],
    )
    assert msg["To"] == "x@y.com"
    assert msg["Subject"] == "hello"
    body = msg.get_body(("plain",))
    assert body is not None and "P1" in body.get_content()
    html_part = msg.get_body(("html",))
    assert html_part is not None and "P1" in html_part.get_content()
    assert "https://e.com/p1" in html_part.get_content()
    attachments = [p for p in _walk_parts(msg) if p.get_filename()]
    assert attachments == []


def test_build_digest_message_attaches_xlsx_when_bytes_provided():
    msg = el_email.build_digest_message(
        to="x@y.com",
        subject="hello",
        narrative="n",
        picks=[],
        xlsx_bytes=b"PK\x03\x04fakezip",
        xlsx_filename="picks.xlsx",
    )
    attachments = [p for p in _walk_parts(msg) if p.get_filename() == "picks.xlsx"]
    assert len(attachments) == 1
    assert attachments[0].get_content_type() == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def test_build_product_detail_message_escapes_html_and_includes_image_link():
    pick = {
        "product_name": "Sneakers <pro>",
        "price_text": "$25",
        "source_url": "https://x.com/<id>",
        "image_url": "https://x.com/img.jpg",
        "why_it_fits": "great fit & comfy",
    }
    msg = el_email.build_product_detail_message(
        to="x@y.com", subject="EL Pick: Sneakers", pick=pick,
    )
    html_part = msg.get_body(("html",)).get_content()
    assert "&lt;pro&gt;" in html_part
    assert "https://x.com/img.jpg" in html_part
    # Escaped ampersand in why_it_fits
    assert "great fit &amp; comfy" in html_part
    assert msg["Subject"] == "EL Pick: Sneakers"


def test_summarize_with_gemini_uses_provider_text():
    class FakeLLM:
        def generate(self, system, user):
            return "Curated set leans toward affordable wireless audio."

    out = el_email.summarize_with_gemini(
        "earbuds", [{"product_name": "Buds", "price_numeric": 25}], provider=FakeLLM(),
    )
    assert "wireless audio" in out


def test_summarize_with_gemini_falls_back_on_exception():
    class BadLLM:
        def generate(self, system, user):
            raise RuntimeError("vertex 500")

    out = el_email.summarize_with_gemini(
        "earbuds",
        [{"product_name": "A", "price_numeric": 10}, {"product_name": "B", "price_numeric": 25}],
        provider=BadLLM(),
    )
    assert "earbuds" in out
    assert "10" in out and "25" in out


def test_summarize_with_gemini_empty_picks_returns_fallback():
    class NeverCalled:
        def generate(self, *_a, **_kw):
            raise AssertionError("should not be called for empty picks")

    out = el_email.summarize_with_gemini("earbuds", [], provider=NeverCalled())
    assert "earbuds" in out


def test_price_formatting_prefers_text_then_numeric():
    msg = el_email.build_digest_message(
        to="x@y.com", subject="s", narrative="",
        picks=[
            {"product_name": "A", "price_text": "₹999"},
            {"product_name": "B", "price_numeric": 25.5, "currency": "USD"},
            {"product_name": "C"},
        ],
    )
    txt = msg.get_body(("plain",)).get_content()
    assert "₹999" in txt
    assert "USD 25.5" in txt
    assert "price n/a" in txt
