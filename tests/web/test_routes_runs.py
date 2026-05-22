"""SP4 — /api/runs route."""
from __future__ import annotations


def test_post_runs_requires_auth(client):
    r = client.post("/api/runs", json={"niche": "x"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "ERR_AUTH"


def test_post_runs_happy_path(client, auth_headers, fake_db):
    r = client.post(
        "/api/runs", headers=auth_headers,
        json={"niche": "wireless earbuds", "dislikes": "loud", "budget_usd": 25},
    )
    assert r.status_code == 202
    body = r.json()
    assert "request_id" in body
    assert body["status"] == "queued"
    # row landed in db
    rid = body["request_id"]
    assert rid in fake_db.rows
    assert fake_db.rows[rid]["niche"] == "wireless earbuds"


def test_post_runs_validation_empty_niche(client, auth_headers):
    r = client.post("/api/runs", headers=auth_headers, json={"niche": ""})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "ERR_VALIDATION"


def test_post_runs_validation_missing_niche(client, auth_headers):
    r = client.post("/api/runs", headers=auth_headers, json={})
    assert r.status_code == 422


def test_get_run_returns_row(client, auth_headers, fake_db):
    fake_db.rows["abc"] = {"id": "abc", "niche": "x", "status": "queued"}
    r = client.get("/api/runs/abc", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["id"] == "abc"


def test_get_run_unknown(client, auth_headers):
    r = client.get("/api/runs/missing", headers=auth_headers)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "ERR_RUN_NOT_FOUND"


def test_get_run_requires_auth(client):
    r = client.get("/api/runs/abc")
    assert r.status_code == 401
