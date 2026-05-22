"""SP4 — bearer-token auth tests."""
from __future__ import annotations

import pytest

from el.web import auth


def test_missing_header_raises():
    with pytest.raises(auth.AuthError):
        auth.verify_bearer(None, expected_secret="secret")


def test_empty_header_raises():
    with pytest.raises(auth.AuthError):
        auth.verify_bearer("", expected_secret="secret")


def test_wrong_scheme_raises():
    with pytest.raises(auth.AuthError):
        auth.verify_bearer("Basic abc123", expected_secret="secret")


def test_wrong_token_raises():
    with pytest.raises(auth.AuthError):
        auth.verify_bearer("Bearer wrong", expected_secret="secret")


def test_correct_token_returns_principal():
    assert auth.verify_bearer("Bearer secret", expected_secret="secret") == "operator"


def test_bearer_lowercase_scheme_accepted():
    """Some clients send 'bearer'. RFC 7235 declares scheme case-insensitive."""
    assert auth.verify_bearer("bearer secret", expected_secret="secret") == "operator"


def test_uses_constant_time_compare(monkeypatch):
    """Verifies we go through hmac.compare_digest (no early-out per-char compare)."""
    import hmac
    calls = {"n": 0}
    real = hmac.compare_digest

    def spy(a, b):
        calls["n"] += 1
        return real(a, b)

    monkeypatch.setattr(auth.hmac, "compare_digest", spy)
    auth.verify_bearer("Bearer secret", expected_secret="secret")
    assert calls["n"] == 1
