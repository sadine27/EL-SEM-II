"""SP4 — /api/runs: submit + status."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from el.logger import get_logger
from el.web import run_service
from el.web.deps import get_principal, get_settings

log = get_logger(__name__)

router = APIRouter(prefix="/api/runs", tags=["runs"])


class RunSubmitBody(BaseModel):
    niche: str = Field(min_length=1, max_length=200)
    dislikes: str = Field(default="", max_length=1000)
    budget_usd: float | None = Field(default=None, ge=0)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def submit_run(
    body: RunSubmitBody,
    background: BackgroundTasks,
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
    request_id = row["id"]
    background.add_task(_run_pipeline_safe, request_id, settings.db_provider)
    return {"request_id": request_id, "status": row["status"]}


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


def _run_pipeline_safe(request_id: str, db_provider) -> None:
    """BackgroundTasks entry. Imports lazily so unrelated tests don't pull in
    the full pipeline graph."""
    try:
        from el.pipeline import run_for_request
        run_for_request(request_id, db_provider=db_provider)
    except Exception:
        log.exception("background pipeline run for %s crashed", request_id)
