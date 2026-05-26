"""SP4 — /api/runs: submit + status."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from el.web import run_service
from el.web.deps import get_principal, get_settings

router = APIRouter(prefix="/api/runs", tags=["runs"])


class RunSubmitBody(BaseModel):
    niche: str = Field(min_length=1, max_length=200)
    dislikes: str = Field(default="", max_length=1000)
    budget_usd: float | None = Field(default=None, ge=0)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def submit_run(
    body: RunSubmitBody,
    request: Request,
    principal: str = Depends(get_principal),
    settings=Depends(get_settings),
):
    row = run_service.submit_run(
        niche=body.niche,
        dislikes=body.dislikes,
        budget_usd=body.budget_usd,
        principal=principal,
        db_provider=settings.db_provider,
    )
    return {"request_id": row["id"], "status": row["status"]}


@router.get("/{request_id}")
def get_run(
    request_id: str,
    _principal: str = Depends(get_principal),
    settings=Depends(get_settings),
):
    row = run_service.get_run(request_id=request_id, db_provider=settings.db_provider)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ERR_RUN_NOT_FOUND", "message": f"no such run {request_id}"},
        )
    return row
