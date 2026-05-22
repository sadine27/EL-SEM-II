"""SP4 FastAPI web layer.

The web app is opt-in: existing pipeline-only deployments leave
EL_WEB_ENABLED=false (the default) and never import this package.

Public surface: ``create_app(settings=None)`` from ``el.web.app``.
"""
from __future__ import annotations

__all__ = ["create_app"]


def create_app(*args, **kwargs):
    """Lazy re-export of el.web.app.create_app to avoid importing FastAPI at
    package import time (keeps non-web tests fast and FastAPI-optional)."""
    from el.web.app import create_app as _create_app
    return _create_app(*args, **kwargs)
