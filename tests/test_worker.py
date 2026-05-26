"""SP8 — background worker that drains private.run_requests."""
from __future__ import annotations

import threading
import time

from tests.web.conftest import FakeDB


class _Pipeline:
    def __init__(self, *, raise_for=None):
        self.calls = []
        self.raise_for = raise_for or set()

    def __call__(self, request_id, *, db_provider):
        self.calls.append(request_id)
        if request_id in self.raise_for:
            raise RuntimeError(f"forced failure for {request_id}")


def _seed_queued(db, n):
    return db.insert_rows(
        schema="private", table="run_requests",
        rows=[{"niche": f"n{i}", "dislikes": "", "budget_usd": None,
               "submitted_by": "u", "status": "queued"} for i in range(n)],
    )


def test_tick_claims_oldest_queued_and_runs_pipeline():
    from el.worker import tick
    db = FakeDB()
    rows = _seed_queued(db, 1)
    pipeline = _Pipeline()
    tick(db_provider=db, worker_id="w", run_pipeline=pipeline)
    assert pipeline.calls == [rows[0]["id"]]
    assert db.rows[rows[0]["id"]]["status"] == "done"


def test_tick_empty_queue_is_noop():
    from el.worker import tick
    db = FakeDB()
    pipeline = _Pipeline()
    tick(db_provider=db, worker_id="w", run_pipeline=pipeline)
    assert pipeline.calls == []


def test_tick_marks_error_on_pipeline_exception():
    from el.worker import tick
    db = FakeDB()
    rows = _seed_queued(db, 1)
    pipeline = _Pipeline(raise_for={rows[0]["id"]})
    tick(db_provider=db, worker_id="w", run_pipeline=pipeline)
    row = db.rows[rows[0]["id"]]
    assert row["status"] == "error"
    assert "forced failure" in row["error_message"]


def test_tick_truncates_long_error_message():
    from el.worker import tick
    db = FakeDB()
    rows = _seed_queued(db, 1)
    long_msg = "x" * 5000

    def boom(rid, **kw):
        raise RuntimeError(long_msg)

    tick(db_provider=db, worker_id="w", run_pipeline=boom)
    assert len(db.rows[rows[0]["id"]]["error_message"]) <= 2000


def test_claim_race_two_workers_one_row():
    """Sequential claim attempts: second sees nothing because first won."""
    from el.web import run_service
    db = FakeDB()
    _seed_queued(db, 1)
    a = run_service.claim_one_queued(worker_id="A", db_provider=db)
    b = run_service.claim_one_queued(worker_id="B", db_provider=db)
    assert a is not None
    assert b is None


def test_run_loop_exits_on_stop_event():
    """SIGTERM/SIGINT sets the event; loop returns within one tick."""
    from el.worker import run_loop
    db = FakeDB()
    pipeline = _Pipeline()
    stop = threading.Event()
    t = threading.Thread(
        target=run_loop,
        kwargs={"db_provider": db, "worker_id": "w",
                "run_pipeline": pipeline, "stop": stop, "poll_seconds": 0.05},
    )
    t.start()
    time.sleep(0.15)
    stop.set()
    t.join(timeout=1.0)
    assert not t.is_alive(), "worker did not exit after stop.set()"
