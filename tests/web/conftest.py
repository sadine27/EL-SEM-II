"""Shared fixtures for SP4 web tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from el import embeddings
from el.web.app import create_app
from el.web.settings import Settings


class FakeDB:
    """In-memory stand-in for SupabaseRestProvider used across route tests."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self._next_id = 1

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
        raw = filters.get("id", "")
        if raw.startswith("eq."):
            key = raw[3:]
            return [self.rows[key]] if key in self.rows else []
        return list(self.rows.values())

    def update_rows(self, *, schema, table, filters, updates):
        raw = filters.get("id", "")
        if not raw.startswith("eq."):
            return []
        key = raw[3:]
        if key not in self.rows:
            return []
        self.rows[key].update(updates)
        return [self.rows[key]]

    def call_rpc(self, *, schema, function, params):
        return []


def _fake_llm_stream(prompt: str):
    yield "hello "
    yield "world"


@pytest.fixture
def fake_db():
    return FakeDB()


@pytest.fixture
def settings(fake_db) -> Settings:
    return Settings(
        web_secret_key="testsecret",
        rate_limit_per_minute=100,
        chat_top_k=3,
        embedding_provider=embeddings.FakeEmbeddingProvider(),
        db_provider=fake_db,
        llm_stream=_fake_llm_stream,
        enabled=True,
    )


@pytest.fixture
def app(settings):
    return create_app(settings=settings)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer testsecret"}
