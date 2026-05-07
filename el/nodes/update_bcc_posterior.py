"""Update Bayesian Beta posteriors after approval/rejection decision."""
from __future__ import annotations

import logging

from el.supabase import SupabaseRestProvider

logger = logging.getLogger(__name__)


def run(ctx: dict, *, provider: SupabaseRestProvider | None = None) -> dict:
    """Update BCC posteriors based on feedback decision.

    Input: ctx["hil_callback_decision"] — {decision: "approved"|"rejected", category: str}
    Output: ctx["bcc_update_result"] — {ok: bool, ...}
    """
    result = {"ok": False, "error": "No update to perform"}

    decision_item = ctx.get("hil_callback_decision")
    if not isinstance(decision_item, dict):
        ctx["bcc_update_result"] = result
        return ctx

    decision = (decision_item.get("decision") or "").strip().lower()
    category = (decision_item.get("category") or "").strip()

    if not category:
        result["error"] = "Missing category"
        ctx["bcc_update_result"] = result
        return ctx

    if decision == "approved":
        alpha_delta = 1
        beta_delta = 0
    elif decision == "rejected":
        alpha_delta = 0
        beta_delta = 1
    else:
        logger.warning(f"Unknown decision: {decision}")
        result["error"] = f"Unknown decision: {decision}"
        ctx["bcc_update_result"] = result
        return ctx

    if provider is None:
        provider = SupabaseRestProvider()

    try:
        # Use raw SQL-like update: increment alpha or beta based on decision
        # The update_rows method applies patch, but we need increment behavior
        # So we'll do it via a custom SQL approach or use upsert pattern

        # For now, use a simpler approach: read current, modify, upsert
        # But to keep it simple and aligned with n8n behavior, we can insert
        # a row if missing and let the trigger handle it, or use a procedure

        # Actually, let's fetch the row first, update it, then upsert
        rows = provider.select_rows(
            schema="private",
            table="bcc_posteriors",
            filters={"category": f"eq.{category}"},
            select="category,alpha,beta",
        )

        if rows and isinstance(rows[0], dict):
            current = rows[0]
            try:
                cur_alpha = float(current.get("alpha") or 1)
            except (TypeError, ValueError):
                cur_alpha = 1.0
            try:
                cur_beta = float(current.get("beta") or 1)
            except (TypeError, ValueError):
                cur_beta = 1.0
            new_alpha = cur_alpha + alpha_delta
            new_beta = cur_beta + beta_delta
        else:
            # Cold-start: insert new row
            new_alpha = 1 + alpha_delta
            new_beta = 1 + beta_delta

        # Upsert the row
        update_rows = [{
            "category": category,
            "alpha": new_alpha,
            "beta": new_beta,
        }]

        upserted = provider.upsert_rows(
            schema="private",
            table="bcc_posteriors",
            rows=update_rows,
            conflict_columns=("category",),
        )

        result = {
            "ok": True,
            "category": category,
            "decision": decision,
            "new_alpha": new_alpha,
            "new_beta": new_beta,
        }
        ctx["bcc_update_result"] = result
    except Exception as e:
        error_result = {
            "ok": False,
            "error": str(e),
            "category": category,
        }
        logger.warning(f"Failed to update BCC posterior for {category}: {e}")
        ctx["bcc_update_result"] = error_result

    return ctx
