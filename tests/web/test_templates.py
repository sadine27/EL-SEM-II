"""SP4 — HTMX template pages."""
from __future__ import annotations


def test_index_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert 'id="niche-form"' in r.text
    assert "hx-post" in r.text  # HTMX wired
    assert "/api/runs" in r.text


def test_run_page(client):
    r = client.get("/run/abc")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert 'id="run-status"' in r.text
    assert "hx-trigger" in r.text  # polling wired
    assert "/api/runs/abc" in r.text


def test_chat_page(client):
    r = client.get("/chat")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert 'id="chat-form"' in r.text
    assert "/api/chat" in r.text


def test_pages_no_auth_required(client):
    # All three HTMX shell pages are public (auth happens at /api/* level).
    for path in ("/", "/run/abc", "/chat"):
        r = client.get(path)
        assert r.status_code == 200, f"{path} returned {r.status_code}"


def test_base_template_loads_htmx_and_tailwind(client):
    r = client.get("/")
    assert "htmx" in r.text.lower()
    assert "tailwindcss" in r.text.lower()
