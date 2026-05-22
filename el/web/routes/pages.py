"""SP4 — HTMX shell pages.

Auth is enforced at the /api/* level; these HTML pages are public so the
operator can land on them and supply the bearer token via the prompt() in
base.html. The pages themselves expose no protected data.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/")
def index(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "index.html", {})


@router.get("/run/{request_id}")
def run_page(request: Request, request_id: str):
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "run.html", {"request_id": request_id})


@router.get("/chat")
def chat_page(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "chat.html", {})
