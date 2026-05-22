"""SP4 — FastAPI dependency callables.

Settings + principal are pulled from app state, so tests can override the
``Settings`` instance with one carrying fake providers (no real Vertex/
Supabase calls).
"""
from __future__ import annotations

from fastapi import Header, Request

from el.web.auth import verify_bearer
from el.web.settings import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_principal(
    request: Request,
    authorization: str | None = Header(default=None),
) -> str:
    settings: Settings = request.app.state.settings
    return verify_bearer(authorization, expected_secret=settings.web_secret_key)
