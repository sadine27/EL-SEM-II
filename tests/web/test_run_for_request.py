"""SP4 — pipeline.run_for_request orchestration tests."""
from __future__ import annotations

import pytest

from el import pipeline


class _FakeDB:
    def __init__(self, *, existing: dict | None = None):
        self.existing = existing
        self.update_calls: list[dict] = []

    def select_rows(self, *, schema, table, filters, select="*", limit=None):
        return [self.existing] if self.existing else []

    def update_rows(self, *, schema, table, filters, updates):
        self.update_calls.append({"filters": filters, "updates": updates})
        return [{"id": "req-1", **updates}]


def _captured_ctxs(monkeypatch) -> list[dict]:
    seen: list[dict] = []

    def fake_run(initial_ctx=None):
        seen.append(initial_ctx or {})
        return initial_ctx or {}

    monkeypatch.setattr(pipeline, "run", fake_run)
    return seen


def test_happy_path_transitions_queued_running_done(monkeypatch):
    db = _FakeDB(existing={
        "id": "req-1", "niche": "earbuds", "dislikes": "loud",
        "budget_usd": 30.0, "status": "queued",
    })
    seen = _captured_ctxs(monkeypatch)

    status = pipeline.run_for_request("req-1", db_provider=db)

    assert status == "done"
    statuses = [c["updates"]["status"] for c in db.update_calls]
    assert statuses == ["running", "done"]
    assert seen[0]["niche"] == "earbuds"
    assert seen[0]["dislikes"] == "loud"
    assert seen[0]["budget_usd"] == 30.0
    assert seen[0]["run_request_id"] == "req-1"


def test_missing_row_raises_before_marking(monkeypatch):
    db = _FakeDB(existing=None)
    _captured_ctxs(monkeypatch)

    with pytest.raises(ValueError, match="not found"):
        pipeline.run_for_request("missing", db_provider=db)

    assert db.update_calls == []


def test_pipeline_failure_marks_error(monkeypatch):
    db = _FakeDB(existing={"id": "req-1", "niche": "x", "dislikes": "", "budget_usd": None})

    def boom(initial_ctx=None):
        raise RuntimeError("pipeline kaboom")

    monkeypatch.setattr(pipeline, "run", boom)

    status = pipeline.run_for_request("req-1", db_provider=db)

    assert status == "error"
    statuses = [c["updates"]["status"] for c in db.update_calls]
    assert statuses == ["running", "error"]
    assert "kaboom" in db.update_calls[-1]["updates"]["error_message"]
