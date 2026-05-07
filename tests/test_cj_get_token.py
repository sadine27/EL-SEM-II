"""Tests for el/nodes/cj_get_token.py."""
from __future__ import annotations

from el.nodes import cj_get_token


class FakeProvider:
    def __init__(self, response: dict | None = None):
        self.response = response or {"data": {"accessToken": "TOKEN"}}
        self.calls = 0

    def get_access_token(self) -> dict:
        self.calls += 1
        return self.response


def test_extract_access_token_from_n8n_response_shape():
    assert cj_get_token._extract_access_token({
        "data": {"accessToken": "TOKEN"}
    }) == "TOKEN"


def test_cj_get_token_stores_response_and_token():
    provider = FakeProvider({"code": 200, "data": {"accessToken": "TOKEN"}})
    ctx = cj_get_token.run({}, provider=provider)
    assert provider.calls == 1
    assert ctx["cj_token_response"] == {"code": 200, "data": {"accessToken": "TOKEN"}}
    assert ctx["cj_access_token"] == "TOKEN"


def test_cj_get_token_fails_soft_when_token_missing():
    """Regression: missing CJ token raised instead of writing an error result."""
    ctx = cj_get_token.run({}, provider=FakeProvider({"data": {}}))
    assert ctx["cj_get_token_result"]["ok"] is False
    assert "missing data.accessToken" in ctx["cj_get_token_result"]["error"]


def test_cj_get_token_handles_non_dict_response():
    """Regression: non-dict CJ token response crashed on response.get."""
    ctx = cj_get_token.run({}, provider=FakeProvider("not-json"))
    assert ctx["cj_get_token_result"]["ok"] is False
