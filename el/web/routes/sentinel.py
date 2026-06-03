"""Item 1.4 — /sentinel monitoring endpoint (read-only dashboard).

Quick visual check of the Sentinel Engine's live pass rate, avg score,
top rejection reasons, top sources, and per-trend stats.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from el import crm
from el.web.deps import get_principal, get_settings

router = APIRouter(tags=["sentinel"])


@router.get("/api/sentinel/summary")
def sentinel_summary(
    limit: int = Query(500, ge=1, le=5000, description="Max rows to analyse"),
    _principal: str = Depends(get_principal),
    settings=Depends(get_settings),
):
    """Aggregate sentinel_log into a monitoring dashboard payload.

    Returns pass rate, avg score, top rejection reasons, top sources,
    and per-trend stats.
    """
    return crm.sentinel_summary(settings.db_provider, limit=limit)
