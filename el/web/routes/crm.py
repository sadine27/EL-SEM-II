"""SP6 — /crm page + /api/crm/* JSON endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from el import crm
from el.web.deps import get_principal, get_settings

router = APIRouter(tags=["crm"])


@router.get("/crm")
def crm_page(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "crm.html", {})


@router.get("/api/crm/niche-performance")
def niche_performance(
    _principal: str = Depends(get_principal),
    settings=Depends(get_settings),
):
    rows = crm.list_niche_performance(settings.db_provider)
    rows_sorted = sorted(rows, key=lambda r: int(r.get("run_count") or 0), reverse=True)
    return rows_sorted


@router.get("/api/crm/suppliers")
def suppliers(
    _principal: str = Depends(get_principal),
    settings=Depends(get_settings),
):
    return crm.list_suppliers(settings.db_provider)


@router.get("/api/crm/disputes")
def disputes(
    _principal: str = Depends(get_principal),
    settings=Depends(get_settings),
):
    return crm.list_disputes(settings.db_provider)
