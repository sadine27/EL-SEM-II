"""SP4 — middleware behavior (rate limit, error envelope)."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from el import embeddings
from el.web.app import create_app
from el.web.settings import Settings
from tests.web.conftest import FakeDB, _fake_llm_stream

_VALID_SA_JSON = json.dumps({
    "type": "service_account",
    "project_id": "p",
    "private_key": "x",
    "client_email": "x@p.iam.gserviceaccount.com",
    "token_uri": "https://oauth2.googleapis.com/token",
})


def _build_client(*, rate_limit_per_minute: int, raise_server_exceptions: bool = True) -> TestClient:
    settings = Settings(
        web_secret_key="testsecret",
        rate_limit_per_minute=rate_limit_per_minute,
        chat_top_k=3,
        embedding_provider=embeddings.FakeEmbeddingProvider(),
        db_provider=FakeDB(),
        llm_stream=_fake_llm_stream,
        google_service_account_json=_VALID_SA_JSON,
        enabled=True,
    )
    app = create_app(settings=settings)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def test_rate_limit_triggers_429():
    client = _build_client(rate_limit_per_minute=2)
    headers = {"Authorization": "Bearer testsecret"}
    r1 = client.post("/api/runs", headers=headers, json={"niche": "x"})
    r2 = client.post("/api/runs", headers=headers, json={"niche": "x"})
    r3 = client.post("/api/runs", headers=headers, json={"niche": "x"})
    assert r1.status_code == 202
    assert r2.status_code == 202
    assert r3.status_code == 429
    body = r3.json()
    assert body["error"]["code"] == "ERR_RATE_LIMIT"
    assert "retry_after" in body["error"]
    assert "Retry-After" in r3.headers


def test_healthz_exempt_from_rate_limit():
    client = _build_client(rate_limit_per_minute=1)
    # Use one token on a protected route, then hit healthz repeatedly.
    headers = {"Authorization": "Bearer testsecret"}
    client.post("/api/runs", headers=headers, json={"niche": "x"})
    for _ in range(5):
        r = client.get("/healthz")
        assert r.status_code == 200


def test_internal_error_envelope(monkeypatch):
    """Uncaught exception in route → 500 ERR_INTERNAL, no stack trace in body."""
    client = _build_client(rate_limit_per_minute=100, raise_server_exceptions=False)
    headers = {"Authorization": "Bearer testsecret"}

    from el.web import run_service

    def boom(**_kw):
        raise RuntimeError("internal kaboom")

    monkeypatch.setattr(run_service, "submit_run", boom)
    r = client.post("/api/runs", headers=headers, json={"niche": "x"})
    assert r.status_code == 500
    body = r.json()
    assert body["error"]["code"] == "ERR_INTERNAL"
    assert "kaboom" not in body["error"]["message"]
