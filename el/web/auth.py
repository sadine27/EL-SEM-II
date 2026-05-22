"""SP4 — bearer-token auth.

Single-operator MVP: every authenticated request carries a shared bearer
token equal to ``Settings.web_secret_key``. Multi-user / Supabase-Auth
magic-link is deferred (see SP4 design spec §1).
"""
from __future__ import annotations

import hmac


class AuthError(Exception):
    """Raised when bearer-token verification fails."""


def verify_bearer(authorization_header: str | None, *, expected_secret: str) -> str:
    """Return the principal name on success, raise AuthError otherwise.

    Header format: ``Bearer <token>`` (scheme is case-insensitive per RFC 7235).
    Token comparison uses ``hmac.compare_digest`` to avoid timing leaks.
    """
    if not authorization_header:
        raise AuthError("missing Authorization header")

    parts = authorization_header.split(" ", 1)
    if len(parts) != 2:
        raise AuthError("malformed Authorization header")

    scheme, token = parts[0], parts[1].strip()
    if scheme.lower() != "bearer":
        raise AuthError("unsupported auth scheme; expected Bearer")

    if not hmac.compare_digest(token, expected_secret):
        raise AuthError("invalid bearer token")

    return "operator"
