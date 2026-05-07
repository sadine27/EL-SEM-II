"""Read Bayesian Beta category priors from Supabase."""
from __future__ import annotations

import logging

from el.supabase import SupabaseRestProvider

logger = logging.getLogger(__name__)


def run(ctx: dict, *, provider: SupabaseRestProvider | None = None) -> dict:
    """Read BCC posteriors from private.bcc_posteriors table.

    Input: nothing (reads from DB)
    Output: ctx["bcc_posteriors"] — list of {category, alpha, beta}
    """
    posteriors = []

    if provider is None:
        provider = SupabaseRestProvider()

    try:
        rows = provider.select_rows(
            schema="private",
            table="bcc_posteriors",
            filters={},
            select="category,alpha,beta",
        )
        posteriors = rows if isinstance(rows, list) else []
    except Exception as e:
        logger.warning(f"Failed to read BCC posteriors: {e}")
        posteriors = []

    ctx["bcc_posteriors"] = posteriors
    return ctx
