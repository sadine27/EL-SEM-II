"""SP6 — Record per-niche CRM metrics at end of each pipeline run."""
from __future__ import annotations

from el import config, crm
from el.logger import get_logger
from el.supabase import SupabaseRestProvider

log = get_logger(__name__)


def _avg_bcc_score(ctx: dict) -> float | None:
    slate = ctx.get("hil_slate") or ctx.get("phase4_candidates") or []
    scores = [
        float(row["opportunity_score"])
        for row in slate
        if isinstance(row, dict) and row.get("opportunity_score") is not None
    ]
    if not scores:
        return None
    return sum(scores) / len(scores)


def run(ctx: dict, *, db_provider: SupabaseRestProvider | None = None) -> dict:
    niche = ctx.get("niche")
    if not niche:
        ctx["crm_niche_performance_result"] = {"ok": True, "skipped": True, "reason": "no_niche"}
        log.info("record_niche_performance: no niche in ctx — skipping")
        return ctx

    if db_provider is None and (
        not config.get("SUPABASE_URL") or not (
            config.get("SUPABASE_SERVICE_ROLE_KEY")
            or config.get("SUPABASE_SECRET_KEY")
            or config.get("SUPABASE_KEY")
        )
    ):
        ctx["crm_niche_performance_result"] = {"ok": True, "skipped": True, "reason": "no_supabase_env"}
        log.info("record_niche_performance: Supabase env vars absent — skipping")
        return ctx

    callback_results = ctx.get("hil_callback_results") or []
    approved = sum(1 for r in callback_results if isinstance(r, dict) and r.get("approval_status") == "approved")
    rejected = sum(1 for r in callback_results if isinstance(r, dict) and r.get("approval_status") == "rejected")
    avg_bcc = _avg_bcc_score(ctx)

    db = db_provider or SupabaseRestProvider()
    try:
        updated = crm.record_niche_run(
            niche,
            approved=approved,
            rejected=rejected,
            avg_bcc_score=avg_bcc,
            db=db,
        )
        ctx["crm_niche_performance_result"] = {
            "ok": True,
            "skipped": False,
            "niche": updated.get("niche") or niche.lower(),
            "run_count": updated.get("run_count"),
            "approval_count": updated.get("approval_count"),
            "rejection_count": updated.get("rejection_count"),
        }
        log.info(
            "record_niche_performance: niche=%r run_count=%s approved=%d rejected=%d",
            niche, updated.get("run_count"), approved, rejected,
        )
    except Exception:
        log.exception("record_niche_performance: DB write failed — fail-soft")
        ctx["crm_niche_performance_result"] = {"ok": False, "skipped": False, "error": "db_write_failed"}

    return ctx
