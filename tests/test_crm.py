"""SP6 — CRM data layer tests."""
from __future__ import annotations

import pytest

from el import crm


class FakeDB:
    def __init__(self, initial_rows=None):
        self._rows: list[dict] = list(initial_rows or [])
        self._upserted: list[dict] = []

    def select_rows(self, *, schema, table, filters, select="*", limit=None):
        results = list(self._rows)
        for key, val in filters.items():
            if val.startswith("eq."):
                expected = val[3:]
                results = [r for r in results if str(r.get(key, "")) == expected]
        if limit:
            results = results[:limit]
        return results

    def upsert_rows(self, *, schema, table, rows, conflict_columns):
        self._upserted.extend(rows)
        return rows


# ---------------------------------------------------------------------------
# list_niche_performance
# ---------------------------------------------------------------------------

def test_list_niche_performance_empty():
    db = FakeDB()
    assert crm.list_niche_performance(db) == []


def test_list_niche_performance_returns_rows():
    rows = [{"niche": "gadgets", "run_count": 3}, {"niche": "toys", "run_count": 1}]
    db = FakeDB(rows)
    result = crm.list_niche_performance(db)
    assert len(result) == 2
    assert result[0]["niche"] == "gadgets"


# ---------------------------------------------------------------------------
# list_suppliers
# ---------------------------------------------------------------------------

def test_list_suppliers_empty():
    assert crm.list_suppliers(FakeDB()) == []


def test_list_suppliers_returns_all():
    rows = [{"supplier_id": 1, "name": "S1", "cj_ref": "CJ001"}]
    assert crm.list_suppliers(FakeDB(rows))[0]["name"] == "S1"


# ---------------------------------------------------------------------------
# list_disputes
# ---------------------------------------------------------------------------

def test_list_disputes_no_filter():
    rows = [
        {"dispute_id": 1, "status": "open"},
        {"dispute_id": 2, "status": "resolved"},
    ]
    result = crm.list_disputes(FakeDB(rows))
    assert len(result) == 2


def test_list_disputes_with_status_filter():
    rows = [
        {"dispute_id": 1, "status": "open"},
        {"dispute_id": 2, "status": "resolved"},
    ]
    result = crm.list_disputes(FakeDB(rows), status="open")
    assert len(result) == 1
    assert result[0]["status"] == "open"


def test_list_disputes_empty():
    assert crm.list_disputes(FakeDB()) == []


# ---------------------------------------------------------------------------
# record_niche_run — new niche (no existing row)
# ---------------------------------------------------------------------------

def test_record_niche_run_new_niche():
    db = FakeDB()
    result = crm.record_niche_run(
        "Gadgets",
        approved=1,
        rejected=0,
        avg_bcc_score=42.5,
        db=db,
    )
    assert result["niche"] == "gadgets"
    assert result["run_count"] == 1
    assert result["approval_count"] == 1
    assert result["rejection_count"] == 0
    assert result["approval_rate"] == 1.0
    assert abs(result["avg_bcc_score"] - 42.5) < 1e-4


def test_record_niche_run_lowercases_niche():
    db = FakeDB()
    result = crm.record_niche_run("GAMING CHAIRS", approved=0, rejected=1, avg_bcc_score=None, db=db)
    assert result["niche"] == "gaming chairs"


def test_record_niche_run_no_bcc_score():
    db = FakeDB()
    result = crm.record_niche_run("toys", approved=0, rejected=0, avg_bcc_score=None, db=db)
    assert "avg_bcc_score" not in result or result.get("avg_bcc_score") is None


# ---------------------------------------------------------------------------
# record_niche_run — existing niche (merges counters)
# ---------------------------------------------------------------------------

def test_record_niche_run_merges_existing():
    existing = {
        "niche": "gadgets",
        "run_count": 5,
        "approval_count": 3,
        "rejection_count": 1,
        "approval_rate": 0.6,
        "avg_bcc_score": 50.0,
    }
    db = FakeDB([existing])
    result = crm.record_niche_run("gadgets", approved=1, rejected=0, avg_bcc_score=60.0, db=db)
    assert result["run_count"] == 6
    assert result["approval_count"] == 4
    assert result["rejection_count"] == 1
    assert abs(result["approval_rate"] - 4 / 6) < 1e-4
    # running mean: (50 * 5 + 60) / 6 = 310/6 ≈ 51.667
    assert abs(result["avg_bcc_score"] - (50.0 * 5 + 60.0) / 6) < 1e-3


def test_record_niche_run_upserts_to_db():
    db = FakeDB()
    crm.record_niche_run("laptops", approved=0, rejected=2, avg_bcc_score=30.0, db=db)
    assert len(db._upserted) == 1
    assert db._upserted[0]["niche"] == "laptops"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def test_merge_running_mean_no_prev():
    assert crm._merge_running_mean(None, 0, 10.0) == 10.0


def test_merge_running_mean_with_prev():
    result = crm._merge_running_mean(20.0, 4, 40.0)
    assert abs(result - (20.0 * 4 + 40.0) / 5) < 1e-9


def test_merge_running_mean_new_none():
    assert crm._merge_running_mean(15.0, 3, None) == 15.0


def test_to_float_none():
    assert crm._to_float(None) is None


def test_to_float_string():
    assert crm._to_float("3.14") == pytest.approx(3.14)


def test_to_float_invalid():
    assert crm._to_float("bad") is None
