"""SP4 + SP8 — /healthz route."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from el import embeddings
from el.web.app import create_app
from el.web.settings import Settings


def _settings(*, db_provider, sa_json=None):
    return Settings(
        web_secret_key="testsecret",
        rate_limit_per_minute=100,
        chat_top_k=3,
        embedding_provider=embeddings.FakeEmbeddingProvider(),
        db_provider=db_provider,
        google_service_account_json=sa_json,
        enabled=True,
    )


def _valid_sa() -> str:
    return json.dumps({
        "type": "service_account",
        "project_id": "p",
        "private_key": "x",
        "client_email": "x@p.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    })


class _DBOk:
    def ping(self): return True
    def insert_rows(self, **kw): return []
    def select_rows(self, **kw): return []
    def update_rows(self, **kw): return []


class _DBDown:
    def ping(self):
        raise TimeoutError("connection timed out")
    def insert_rows(self, **kw): return []
    def select_rows(self, **kw): return []
    def update_rows(self, **kw): return []


def test_healthz_ok_when_db_and_creds_ok():
    s = _settings(db_provider=_DBOk(), sa_json=_valid_sa())
    c = TestClient(create_app(settings=s))
    r = c.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["checks"]["db"] == "ok"
    assert body["checks"]["vertex_creds"] == "ok"


def test_healthz_503_when_db_fails():
    s = _settings(db_provider=_DBDown(), sa_json=_valid_sa())
    c = TestClient(create_app(settings=s))
    r = c.get("/healthz")
    assert r.status_code == 503
    body = r.json()
    assert body["ok"] is False
    assert body["checks"]["db"].startswith("error:")
    assert body["checks"]["vertex_creds"] == "ok"


def test_healthz_503_when_sa_missing():
    s = _settings(db_provider=_DBOk(), sa_json=None)
    c = TestClient(create_app(settings=s))
    r = c.get("/healthz")
    assert r.status_code == 503
    assert r.json()["checks"]["vertex_creds"].startswith("error:")


def test_healthz_503_when_sa_invalid_json():
    s = _settings(db_provider=_DBOk(), sa_json="{not json")
    c = TestClient(create_app(settings=s))
    r = c.get("/healthz")
    assert r.status_code == 503
    assert r.json()["checks"]["vertex_creds"].startswith("error:")


def test_healthz_no_network_for_vertex_check(monkeypatch):
    """The check must not make outbound network calls."""
    def _boom(*a, **kw):
        raise AssertionError("network call attempted in healthz")
    monkeypatch.setattr("requests.get", _boom)
    monkeypatch.setattr("requests.post", _boom)
    s = _settings(db_provider=_DBOk(), sa_json=_valid_sa())
    c = TestClient(create_app(settings=s))
    r = c.get("/healthz")
    assert r.status_code == 200
