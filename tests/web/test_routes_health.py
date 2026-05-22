"""SP4 — /healthz route."""
from __future__ import annotations


def test_healthz_no_auth_required(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "version" in body
