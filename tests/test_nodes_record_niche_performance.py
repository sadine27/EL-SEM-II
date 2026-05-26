"""SP6 — record_niche_performance node tests."""
from __future__ import annotations

import pytest

from el.nodes import record_niche_performance


class FakeDB:
    def __init__(self):
        self.calls: list[dict] = []
        self._rows: list[dict] = []

    def select_rows(self, *, schema, table, filters, select="*", limit=None):
        return []

    def upsert_rows(self, *, schema, table, rows, conflict_columns):
        self.calls.extend(rows)
        return rows


# ---------------------------------------------------------------------------
# skip paths
# ---------------------------------------------------------------------------

def test_skips_when_no_niche():
    ctx = {}
    result = record_niche_performance.run(ctx)
    r = result["crm_niche_performance_result"]
    assert r["ok"] is True
    assert r["skipped"] is True
    assert r["reason"] == "no_niche"


def test_skips_when_no_supabase_env(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    ctx = {"niche": "gadgets"}
    result = record_niche_performance.run(ctx)
    r = result["crm_niche_performance_result"]
    assert r["ok"] is True
    assert r["skipped"] is True
    assert r["reason"] == "no_supabase_env"


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------

def test_happy_path_no_callbacks():
    db = FakeDB()
    ctx = {"niche": "wireless earbuds"}
    result = record_niche_performance.run(ctx, db_provider=db)
    r = result["crm_niche_performance_result"]
    assert r["ok"] is True
    assert r["skipped"] is False
    assert r["niche"] == "wireless earbuds"
    assert r["run_count"] == 1
    assert len(db.calls) == 1


def test_happy_path_with_approvals():
    db = FakeDB()
    ctx = {
        "niche": "gaming chairs",
        "hil_callback_results": [
            {"approval_status": "approved"},
            {"approval_status": "rejected"},
        ],
        "hil_slate": [
            {"opportunity_score": 80},
            {"opportunity_score": 60},
        ],
    }
    result = record_niche_performance.run(ctx, db_provider=db)
    r = result["crm_niche_performance_result"]
    assert r["approval_count"] == 1
    assert r["rejection_count"] == 1
    upserted = db.calls[0]
    assert upserted["niche"] == "gaming chairs"
    assert abs(upserted["avg_bcc_score"] - 70.0) < 1e-4


def test_bcc_score_from_phase4_candidates_fallback():
    db = FakeDB()
    ctx = {
        "niche": "toys",
        "phase4_candidates": [{"opportunity_score": 55}],
    }
    result = record_niche_performance.run(ctx, db_provider=db)
    upserted = db.calls[0]
    assert abs(upserted["avg_bcc_score"] - 55.0) < 1e-4


def test_no_bcc_score_when_slate_empty():
    db = FakeDB()
    ctx = {"niche": "laptops", "hil_slate": []}
    record_niche_performance.run(ctx, db_provider=db)
    upserted = db.calls[0]
    assert "avg_bcc_score" not in upserted


# ---------------------------------------------------------------------------
# fail-soft on DB error
# ---------------------------------------------------------------------------

class BrokenDB:
    def select_rows(self, **kwargs):
        raise RuntimeError("connection refused")

    def upsert_rows(self, **kwargs):
        raise RuntimeError("connection refused")


def test_fail_soft_on_db_error():
    ctx = {"niche": "watches"}
    result = record_niche_performance.run(ctx, db_provider=BrokenDB())
    r = result["crm_niche_performance_result"]
    assert r["ok"] is False
    assert r["error"] == "db_write_failed"
