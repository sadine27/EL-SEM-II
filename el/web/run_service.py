"""SP4 — pure helpers around private.run_requests.

No FastAPI imports here; this is the durable-state contract used by both
the HTTP route handlers and the BackgroundTasks worker.
"""
from __future__ import annotations

from datetime import datetime, timezone

from el.supabase import RUN_REQUESTS_SCHEMA, RUN_REQUESTS_TABLE

_ERROR_MESSAGE_MAX_LEN = 2000


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def submit_run(
    *,
    niche: str,
    dislikes: str,
    budget_usd: float | None,
    principal: str,
    db_provider,
) -> dict:
    """Insert a queued run request and return the resulting row."""
    rows = db_provider.insert_rows(
        schema=RUN_REQUESTS_SCHEMA,
        table=RUN_REQUESTS_TABLE,
        rows=[{
            "niche": niche,
            "dislikes": dislikes,
            "budget_usd": budget_usd,
            "submitted_by": principal,
            "status": "queued",
        }],
    )
    return rows[0]


def get_run(*, request_id: str, db_provider) -> dict | None:
    rows = db_provider.select_rows(
        schema=RUN_REQUESTS_SCHEMA,
        table=RUN_REQUESTS_TABLE,
        filters={"id": f"eq.{request_id}"},
        limit=1,
    )
    return rows[0] if rows else None


def mark_running(*, request_id: str, pipeline_run_id: str | None, db_provider) -> None:
    db_provider.update_rows(
        schema=RUN_REQUESTS_SCHEMA,
        table=RUN_REQUESTS_TABLE,
        filters={"id": f"eq.{request_id}"},
        updates={
            "status": "running",
            "pipeline_run_id": pipeline_run_id,
            "started_at": _now_iso(),
        },
    )


def mark_done(*, request_id: str, db_provider) -> None:
    db_provider.update_rows(
        schema=RUN_REQUESTS_SCHEMA,
        table=RUN_REQUESTS_TABLE,
        filters={"id": f"eq.{request_id}"},
        updates={"status": "done", "finished_at": _now_iso()},
    )


def mark_error(*, request_id: str, error_message: str, db_provider) -> None:
    db_provider.update_rows(
        schema=RUN_REQUESTS_SCHEMA,
        table=RUN_REQUESTS_TABLE,
        filters={"id": f"eq.{request_id}"},
        updates={
            "status": "error",
            "error_message": error_message[:_ERROR_MESSAGE_MAX_LEN],
            "finished_at": _now_iso(),
        },
    )


def claim_one_queued(*, worker_id: str, db_provider) -> dict | None:
    """Atomic claim of the oldest queued run.

    Two-step (find oldest queued -> conditional update with status=queued
    guard) so concurrent workers cannot both win the same row. With
    deploy.replicas=1 this is also a defense-in-depth measure.
    """
    candidates = db_provider.select_rows(
        schema=RUN_REQUESTS_SCHEMA,
        table=RUN_REQUESTS_TABLE,
        filters={"status": "eq.queued"},
        limit=1,
    )
    if not candidates:
        return None
    row_id = candidates[0]["id"]
    claimed = db_provider.update_rows(
        schema=RUN_REQUESTS_SCHEMA,
        table=RUN_REQUESTS_TABLE,
        filters={"id": f"eq.{row_id}", "status": "eq.queued"},
        updates={
            "status": "running",
            "claimed_by": worker_id,
            "started_at": _now_iso(),
        },
    )
    return claimed[0] if claimed else None
