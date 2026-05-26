"""SP6 — /crm page + /api/crm/* route tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from el import embeddings
from el.web.app import create_app
from el.web.settings import Settings


class FakeCRMDB:
    """In-memory DB that handles both run_requests (SP4) and CRM tables."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self._next_id = 1
        self._niche_rows: list[dict] = []
        self._supplier_rows: list[dict] = []
        self._dispute_rows: list[dict] = []

    # SP4 run_requests compat
    def insert_rows(self, *, schema, table, rows):
        out = []
        for r in rows:
            row_id = r.get("id") or f"req-{self._next_id}"
            self._next_id += 1
            row = {"id": row_id, **r}
            self.rows[row_id] = row
            out.append(row)
        return out

    def select_rows(self, *, schema, table, filters, select="*", limit=None):
        if table == "niche_performance":
            return list(self._niche_rows)
        if table == "suppliers":
            return list(self._supplier_rows)
        if table == "disputes":
            rows = list(self._dispute_rows)
            for key, val in filters.items():
                if val.startswith("eq."):
                    expected = val[3:]
                    rows = [r for r in rows if str(r.get(key, "")) == expected]
            return rows
        # default: run_requests
        def _matches(row):
            for key, raw in filters.items():
                if not raw.startswith("eq."):
                    return False
                if str(row.get(key)) != raw[3:]:
                    return False
            return True
        matched = [r for r in self.rows.values() if _matches(r)]
        if limit is not None:
            matched = matched[:limit]
        return matched

    def update_rows(self, *, schema, table, filters, updates):
        return []

    def call_rpc(self, *, schema, function, params):
        return []

    def upsert_rows(self, *, schema, table, rows, conflict_columns):
        return rows


def _fake_llm_stream(prompt: str):
    yield "ok"


@pytest.fixture
def crm_db():
    return FakeCRMDB()


@pytest.fixture
def crm_settings(crm_db):
    return Settings(
        web_secret_key="testsecret",
        rate_limit_per_minute=100,
        chat_top_k=3,
        embedding_provider=embeddings.FakeEmbeddingProvider(),
        db_provider=crm_db,
        llm_stream=_fake_llm_stream,
        enabled=True,
    )


@pytest.fixture
def crm_client(crm_settings):
    return TestClient(create_app(settings=crm_settings))


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer testsecret"}


# ---------------------------------------------------------------------------
# GET /crm  (shell page — public)
# ---------------------------------------------------------------------------

def test_crm_page_returns_200(crm_client):
    r = crm_client.get("/crm")
    assert r.status_code == 200
    assert "CRM" in r.text


def test_crm_page_has_nav_link(crm_client):
    r = crm_client.get("/crm")
    assert "/crm" in r.text


# ---------------------------------------------------------------------------
# GET /api/crm/niche-performance
# ---------------------------------------------------------------------------

def test_niche_performance_requires_auth(crm_client):
    r = crm_client.get("/api/crm/niche-performance")
    assert r.status_code == 401


def test_niche_performance_empty(crm_client, auth_headers):
    r = crm_client.get("/api/crm/niche-performance", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == []


def test_niche_performance_returns_rows(crm_client, auth_headers, crm_db):
    crm_db._niche_rows = [
        {"niche": "gadgets", "run_count": 5, "approval_rate": 0.8},
        {"niche": "toys", "run_count": 2, "approval_rate": 0.5},
    ]
    r = crm_client.get("/api/crm/niche-performance", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    # sorted by run_count desc
    assert data[0]["niche"] == "gadgets"
    assert data[1]["niche"] == "toys"


# ---------------------------------------------------------------------------
# GET /api/crm/suppliers
# ---------------------------------------------------------------------------

def test_suppliers_requires_auth(crm_client):
    r = crm_client.get("/api/crm/suppliers")
    assert r.status_code == 401


def test_suppliers_empty(crm_client, auth_headers):
    r = crm_client.get("/api/crm/suppliers", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == []


def test_suppliers_returns_rows(crm_client, auth_headers, crm_db):
    crm_db._supplier_rows = [{"supplier_id": 1, "name": "Acme", "cj_ref": "CJ01"}]
    r = crm_client.get("/api/crm/suppliers", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data[0]["name"] == "Acme"


# ---------------------------------------------------------------------------
# GET /api/crm/disputes
# ---------------------------------------------------------------------------

def test_disputes_requires_auth(crm_client):
    r = crm_client.get("/api/crm/disputes")
    assert r.status_code == 401


def test_disputes_empty(crm_client, auth_headers):
    r = crm_client.get("/api/crm/disputes", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == []


def test_disputes_returns_rows(crm_client, auth_headers, crm_db):
    crm_db._dispute_rows = [
        {"dispute_id": 1, "status": "open", "product_key": "http://a.com/p1"},
        {"dispute_id": 2, "status": "resolved", "product_key": "http://a.com/p2"},
    ]
    r = crm_client.get("/api/crm/disputes", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()) == 2
