"""SP6 — CRM minimal data access layer + Sentinel monitoring.

Three read helpers for the /crm dashboard, plus record_niche_run which
upserts niche_performance with merged cumulative counters.

Also provides ``sentinel_summary()`` for the Sentinel monitoring dashboard
(Item 1.3): pass rate, avg score, top rejection reasons, top sources,
per-trend stats.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from el.supabase import (
    CRM_DISPUTES_TABLE,
    CRM_NICHE_PERFORMANCE_TABLE,
    CRM_SCHEMA,
    CRM_SUPPLIERS_TABLE,
    SupabaseRestProvider,
)

SENTINEL_LOG_TABLE = "sentinel_log"



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


# --------------------------------------------------------------------------- #
# Sentinel monitoring (Item 1.3)                                             #
# --------------------------------------------------------------------------- #
def sentinel_summary(
    db: SupabaseRestProvider,
    *,
    limit: int = 500,
) -> dict[str, Any]:
    """Aggregate sentinel_log for the Sentinel monitoring dashboard.

    Returns a dict with:
      - total_logged       — total rows analysed
      - pass_count         — number of PASS decisions
      - reject_count       — number of REJECT decisions
      - pass_rate          — pass_count / total_logged
      - avg_score          — mean sentinel_score across PASS rows
      - top_rejection_reasons — top-10 rejection reason codes
      - top_sources        — top-10 source_ids by volume
      - per_trend_stats    — per-query breakdown (query, total, pass, reject,
                             pass_rate, avg_score)
    """
    rows = db.select_rows(
        schema=CRM_SCHEMA,
        table=SENTINEL_LOG_TABLE,
        filters={},
        select="*",
        limit=limit,
    )
    total = len(rows)
    if total == 0:
        return {
            "total_logged": 0,
            "pass_count": 0,
            "reject_count": 0,
            "pass_rate": 0.0,
            "avg_score": None,
            "top_rejection_reasons": [],
            "top_sources": [],
            "per_trend_stats": [],
        }

    passed = [r for r in rows if r.get("sentinel_decision") == "pass"]
    rejected = [r for r in rows if r.get("sentinel_decision") == "reject"]
    pass_rate = round(len(passed) / total, 4)

    scores = [float(r["sentinel_score"]) for r in passed if r.get("sentinel_score") is not None]
    avg_score = round(sum(scores) / len(scores), 4) if scores else None

    # Top rejection reasons: flatten all rejection_reasons arrays
    reason_counter: dict[str, int] = {}
    for r in rows:
        reasons = r.get("rejection_reasons") or []
        if isinstance(reasons, list):
            for reason in reasons:
                code = reason if isinstance(reason, str) else (reason.get("reason") or reason.get("code") or str(reason))
                reason_counter[code] = reason_counter.get(code, 0) + 1
        elif isinstance(reasons, str):
            reason_counter[reasons] = reason_counter.get(reasons, 0) + 1
    top_reasons = sorted(reason_counter.items(), key=lambda kv: -kv[1])[:10]
    top_rejection_reasons = [{"reason": r, "count": c} for r, c in top_reasons]

    # Top sources
    source_counter: dict[str, int] = {}
    for r in rows:
        sid = r.get("source_id") or "unknown"
        source_counter[sid] = source_counter.get(sid, 0) + 1
    top_sources = sorted(source_counter.items(), key=lambda kv: -kv[1])[:10]
    top_sources_list = [{"source_id": s, "count": c} for s, c in top_sources]

    # Per-trend stats
    trend_map: dict[str, list] = {}
    for r in rows:
        q = r.get("query") or "unknown"
        trend_map.setdefault(q, []).append(r)
    per_trend = []
    for q, trend_rows in sorted(trend_map.items(), key=lambda kv: -len(kv[1])):
        t_total = len(trend_rows)
        t_pass = sum(1 for r in trend_rows if r.get("sentinel_decision") == "pass")
        t_reject = t_total - t_pass
        t_scores = [
            float(r["sentinel_score"]) for r in trend_rows
            if r.get("sentinel_decision") == "pass" and r.get("sentinel_score") is not None
        ]
        t_avg = round(sum(t_scores) / len(t_scores), 4) if t_scores else None
        per_trend.append({
            "query": q,
            "total": t_total,
            "pass": t_pass,
            "reject": t_reject,
            "pass_rate": round(t_pass / t_total, 4) if t_total > 0 else 0.0,
            "avg_score": t_avg,
        })

    return {
        "total_logged": total,
        "pass_count": len(passed),
        "reject_count": len(rejected),
        "pass_rate": pass_rate,
        "avg_score": avg_score,
        "top_rejection_reasons": top_rejection_reasons,
        "top_sources": top_sources_list,
        "per_trend_stats": per_trend,
    }
