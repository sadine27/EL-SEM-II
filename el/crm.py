"""SP6 — CRM minimal data access layer.

Three read helpers for the /crm dashboard, plus record_niche_run which
upserts niche_performance with merged cumulative counters.
"""
from __future__ import annotations

from datetime import datetime, timezone

from el.supabase import (
    CRM_DISPUTES_TABLE,
    CRM_NICHE_PERFORMANCE_TABLE,
    CRM_SCHEMA,
    CRM_SUPPLIERS_TABLE,
    SupabaseRestProvider,
)


def list_niche_performance(db: SupabaseRestProvider) -> list[dict]:
    return db.select_rows(
        schema=CRM_SCHEMA,
        table=CRM_NICHE_PERFORMANCE_TABLE,
        filters={},
        select="*",
    )


def list_suppliers(db: SupabaseRestProvider) -> list[dict]:
    return db.select_rows(
        schema=CRM_SCHEMA,
        table=CRM_SUPPLIERS_TABLE,
        filters={},
        select="*",
    )


def list_disputes(
    db: SupabaseRestProvider,
    *,
    status: str | None = None,
) -> list[dict]:
    filters: dict[str, str] = {}
    if status is not None:
        filters["status"] = f"eq.{status}"
    return db.select_rows(
        schema=CRM_SCHEMA,
        table=CRM_DISPUTES_TABLE,
        filters=filters,
        select="*",
    )


def record_niche_run(
    niche: str,
    *,
    approved: int,
    rejected: int,
    avg_bcc_score: float | None,
    db: SupabaseRestProvider,
) -> dict:
    """Upsert niche_performance for one pipeline run.

    Fetches the current row (if any), merges incremental counters, then
    upserts. Atomic enough for our single-writer pipeline cadence.
    """
    key = niche.strip().lower()
    now = datetime.now(timezone.utc).isoformat()

    existing_rows = db.select_rows(
        schema=CRM_SCHEMA,
        table=CRM_NICHE_PERFORMANCE_TABLE,
        filters={"niche": f"eq.{key}"},
        limit=1,
    )
    existing = existing_rows[0] if existing_rows else {}

    prev_run_count = int(existing.get("run_count") or 0)
    prev_approval_count = int(existing.get("approval_count") or 0)
    prev_rejection_count = int(existing.get("rejection_count") or 0)
    prev_avg_bcc = _to_float(existing.get("avg_bcc_score"))

    new_run_count = prev_run_count + 1
    new_approval_count = prev_approval_count + approved
    new_rejection_count = prev_rejection_count + rejected
    new_approval_rate = new_approval_count / new_run_count if new_run_count > 0 else 0.0
    new_avg_bcc = _merge_running_mean(prev_avg_bcc, prev_run_count, avg_bcc_score)

    row = {
        "niche": key,
        "run_count": new_run_count,
        "approval_count": new_approval_count,
        "rejection_count": new_rejection_count,
        "approval_rate": round(new_approval_rate, 4),
        "last_run_at": now,
        "updated_at": now,
    }
    if new_avg_bcc is not None:
        row["avg_bcc_score"] = round(new_avg_bcc, 6)

    rows = db.upsert_rows(
        schema=CRM_SCHEMA,
        table=CRM_NICHE_PERFORMANCE_TABLE,
        rows=[row],
        conflict_columns=("niche",),
    )
    return rows[0] if rows else row


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _merge_running_mean(
    prev_mean: float | None,
    prev_n: int,
    new_value: float | None,
) -> float | None:
    if new_value is None:
        return prev_mean
    if prev_mean is None or prev_n == 0:
        return new_value
    return (prev_mean * prev_n + new_value) / (prev_n + 1)
