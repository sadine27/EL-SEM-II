"""SP4 — run_service pure-helper tests."""
from __future__ import annotations

from el.web import run_service


class _FakeDB:
    def __init__(self, *, select_results: list[dict] | None = None):
        self.insert_calls: list[dict] = []
        self.select_calls: list[dict] = []
        self.update_calls: list[dict] = []
        self._select_results = select_results or []

    def insert_rows(self, *, schema, table, rows):
        self.insert_calls.append({"schema": schema, "table": table, "rows": rows})
        return [{"id": "req-uuid-1", **r} for r in rows]

    def select_rows(self, *, schema, table, filters, select="*", limit=None):
        self.select_calls.append({
            "schema": schema, "table": table, "filters": filters,
            "select": select, "limit": limit,
        })
        return self._select_results

    def update_rows(self, *, schema, table, filters, updates):
        self.update_calls.append({
            "schema": schema, "table": table, "filters": filters, "updates": updates,
        })
        return [{"id": "req-uuid-1", **updates}]


def test_submit_run_inserts_row_with_expected_fields():
    db = _FakeDB()
    row = run_service.submit_run(
        niche="wireless earbuds", dislikes="loud bass", budget_usd=25.0,
        principal="operator", db_provider=db,
    )
    assert db.insert_calls[0]["schema"] == "private"
    assert db.insert_calls[0]["table"] == "run_requests"
    inserted = db.insert_calls[0]["rows"][0]
    assert inserted["niche"] == "wireless earbuds"
    assert inserted["dislikes"] == "loud bass"
    assert inserted["budget_usd"] == 25.0
    assert inserted["submitted_by"] == "operator"
    assert inserted["status"] == "queued"
    assert row["id"] == "req-uuid-1"


def test_submit_run_with_no_budget():
    db = _FakeDB()
    run_service.submit_run(
        niche="x", dislikes="", budget_usd=None,
        principal="operator", db_provider=db,
    )
    assert db.insert_calls[0]["rows"][0]["budget_usd"] is None


def test_get_run_returns_row():
    db = _FakeDB(select_results=[{"id": "abc", "status": "queued"}])
    row = run_service.get_run(request_id="abc", db_provider=db)
    assert row == {"id": "abc", "status": "queued"}
    assert db.select_calls[0]["filters"] == {"id": "eq.abc"}


def test_get_run_unknown_returns_none():
    db = _FakeDB(select_results=[])
    assert run_service.get_run(request_id="missing", db_provider=db) is None


def test_mark_running_sets_status_and_pipeline_run_id():
    db = _FakeDB()
    run_service.mark_running(
        request_id="abc", pipeline_run_id="pl-1", db_provider=db,
    )
    call = db.update_calls[0]
    assert call["filters"] == {"id": "eq.abc"}
    assert call["updates"]["status"] == "running"
    assert call["updates"]["pipeline_run_id"] == "pl-1"
    assert "started_at" in call["updates"]


def test_mark_done_sets_status_and_finished_at():
    db = _FakeDB()
    run_service.mark_done(request_id="abc", db_provider=db)
    call = db.update_calls[0]
    assert call["updates"]["status"] == "done"
    assert "finished_at" in call["updates"]


def test_mark_error_records_truncated_message():
    db = _FakeDB()
    long = "boom " * 1000
    run_service.mark_error(request_id="abc", error_message=long, db_provider=db)
    call = db.update_calls[0]
    assert call["updates"]["status"] == "error"
    assert len(call["updates"]["error_message"]) <= 2000
    assert "finished_at" in call["updates"]
