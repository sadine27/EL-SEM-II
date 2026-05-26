"""SP4 — FastAPI app factory.

Tests construct an app via ``create_app(settings=Settings(...))`` with fake
providers wired in. Production entrypoint is ``el.web:create_app`` (called
by ``uvicorn el.web:create_app --factory``); it builds Settings from env.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from el.web.errors import register_error_handlers
from el.web.rate_limit import TokenBucket
from el.web.routes.chat import router as chat_router
from el.web.routes.crm import router as crm_router
from el.web.routes.health import router as health_router
from el.web.routes.pages import router as pages_router
from el.web.routes.runs import router as runs_router
from el.web.settings import Settings


_RATE_LIMIT_EXEMPT_PREFIXES = ("/healthz", "/static")
_WEB_DIR = Path(__file__).resolve().parent


def create_app(*, settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = Settings.from_env()

    app = FastAPI(title="EL Phase 3 SaaS", version="sp4")
    app.state.settings = settings
    app.state.rate_limiter = TokenBucket.per_minute(settings.rate_limit_per_minute)
    app.state.templates = Jinja2Templates(directory=str(_WEB_DIR / "templates"))
    app.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")

    @app.middleware("http")
    async def _rate_limit_mw(request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in _RATE_LIMIT_EXEMPT_PREFIXES):
            return await call_next(request)
        key = request.client.host if request.client else "unknown"
        allowed, retry_after = app.state.rate_limiter.try_consume(key)
        if not allowed:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(int(retry_after) + 1)},
                content={"error": {
                    "code": "ERR_RATE_LIMIT",
                    "message": "too many requests",
                    "retry_after": retry_after,
                }},
            )
        return await call_next(request)

    register_error_handlers(app)

    app.include_router(health_router)
    app.include_router(runs_router)
    app.include_router(chat_router)
    app.include_router(crm_router)
    app.include_router(pages_router)

    return app
