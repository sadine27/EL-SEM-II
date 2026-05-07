"""Tests for el/nodes/cj_product_list.py."""
from __future__ import annotations

from el.nodes import cj_product_list


class FakeProvider:
    def __init__(self, responses: list[dict] | None = None, errors: list[Exception] | None = None):
        self.responses = responses or [{"data": {"list": []}}]
        self.errors = errors or []
        self.calls: list[tuple[str, str]] = []

    def list_products(self, keyword: str, access_token: str) -> dict:
        self.calls.append((keyword, access_token))
        if self.errors:
            raise self.errors.pop(0)
        return self.responses.pop(0) if self.responses else {"data": {"list": []}}


def test_cj_product_list_fetches_each_keyword():
    provider = FakeProvider([
        {"data": {"list": [{"pid": "1"}]}},
        {"data": {"list": [{"pid": "2"}]}},
    ])
    sleeps: list[float] = []
    ctx = cj_product_list.run(
        {
            "cj_access_token": "TOKEN",
            "cj_search_queries": [
                {"keyword": "wireless earbuds", "source_topic": "T1"},
                {"keyword": "phone case", "source_topic": "T2"},
            ],
        },
        provider=provider,
        sleep=sleeps.append,
    )
    assert provider.calls == [("wireless earbuds", "TOKEN"), ("phone case", "TOKEN")]
    assert sleeps == [cj_product_list.DEFAULT_BATCH_INTERVAL]
    assert ctx["cj_product_list_responses"] == [
        {
            "query": {"keyword": "wireless earbuds", "source_topic": "T1"},
            "response": {"data": {"list": [{"pid": "1"}]}},
            "ok": True,
        },
        {
            "query": {"keyword": "phone case", "source_topic": "T2"},
            "response": {"data": {"list": [{"pid": "2"}]}},
            "ok": True,
        },
    ]


def test_cj_product_list_retries_then_succeeds():
    provider = FakeProvider(
        responses=[{"data": {"list": [{"pid": "ok"}]}}],
        errors=[RuntimeError("temporary")],
    )
    sleeps: list[float] = []
    ctx = cj_product_list.run(
        {"cj_access_token": "TOKEN", "cj_search_queries": [{"keyword": "earbuds"}]},
        provider=provider,
        wait_between_tries=0.25,
        sleep=sleeps.append,
    )
    assert provider.calls == [("earbuds", "TOKEN"), ("earbuds", "TOKEN")]
    assert sleeps == [0.25]
    assert ctx["cj_product_list_responses"][0]["ok"] is True


def test_cj_product_list_continue_on_final_failure():
    provider = FakeProvider(errors=[RuntimeError("quota"), RuntimeError("quota")])
    sleeps: list[float] = []
    ctx = cj_product_list.run(
        {"cj_access_token": "TOKEN", "cj_search_queries": [{"keyword": "earbuds"}]},
        provider=provider,
        max_tries=2,
        wait_between_tries=0.1,
        sleep=sleeps.append,
    )
    assert sleeps == [0.1]
    assert ctx["cj_product_list_responses"] == [{
        "query": {"keyword": "earbuds"},
        "ok": False,
        "error": "quota",
    }]


def test_cj_product_list_skips_without_queries():
    provider = FakeProvider()
    ctx = cj_product_list.run({"cj_access_token": "TOKEN"}, provider=provider)
    assert provider.calls == []
    assert ctx["cj_product_list_responses"] == []


def test_cj_product_list_fails_soft_without_token():
    """Regression: missing CJ access token raised instead of per-query errors."""
    ctx = cj_product_list.run({"cj_search_queries": [{"keyword": "earbuds"}]},
                              provider=FakeProvider())
    assert ctx["cj_product_list_responses"] == [{
        "query": {"keyword": "earbuds"},
        "ok": False,
        "error": "Missing cj_access_token",
    }]


def test_cj_product_list_handles_non_dict_query_item():
    """Regression: non-dict CJ query item crashed on query.get."""
    ctx = cj_product_list.run(
        {"cj_access_token": "TOKEN", "cj_search_queries": [None]},
        provider=FakeProvider(),
        sleep=lambda _: None,
    )
    assert ctx["cj_product_list_responses"] == [{
        "query": {},
        "ok": False,
        "error": "Invalid query item",
    }]
