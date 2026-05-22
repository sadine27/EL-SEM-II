"""SP4 — stable JSON error envelope + handler registration.

Every error returned by the FastAPI app uses this envelope. No HTML stack
traces leak; codes are stable for client error-handling.
"""
from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from el.logger import get_logger
from el.web.auth import AuthError

log = get_logger(__name__)


def err(code: str, message: str, **extra) -> dict:
    body = {"error": {"code": code, "message": message}}
    if extra:
        body["error"].update(extra)
    return body


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthError)
    async def _auth(_request: Request, exc: AuthError):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=err("ERR_AUTH", str(exc)),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=err("ERR_VALIDATION", "invalid request body", errors=exc.errors()),
        )

    @app.exception_handler(Exception)
    async def _internal(_request: Request, exc: Exception):
        log.exception("unhandled exception in route")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=err("ERR_INTERNAL", "internal server error"),
        )
