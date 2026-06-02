"""Regression tests for final hardening edge cases."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import requests

from el import llm
from el.nodes import (
    answer_hil_callback,
    browserbase_fetch,
    build_tavily_query,
    delete_hil_message,
    edit_hil_message,
    gemini_extract_product,
    if_tavily_content_thin,
    log_hil_message_deleted,
    log_hil_message_edited,
    normalize_browserbase_review,
    pick_indian_listings,
    pick_top_3,
    prepare_gemini_prompt,
    score_rank,
    send_hil_telegram_photo,
    send_hil_telegram_text_fallback,
    strip_html,
    tavily_search_in_market,
    telegram_alert,
    update_bcc_posterior,
)


def _raise_default():
    raise RuntimeError("missing credentials")


def test_telegram_default_provider_failures_are_collected(monkeypatch):
    """Regression: Telegram provider init failures escaped callback/photo/text nodes."""
    monkeypatch.setattr(answer_hil_callback, "default_provider", _raise_default)
    monkeypatch.setattr(send_hil_telegram_photo, "default_provider", _raise_default)
    monkeypatch.setattr(send_hil_telegram_text_fallback, "default_provider", _raise_default)

    answer_ctx = answer_hil_callback.run({"hil_callback_results": [{"callback_query_id": "c"}]})
    photo_ctx = send_hil_telegram_photo.run({"telegram_photo_cards": [{"review_id": 1}]})
    text_ctx = send_hil_telegram_text_fallback.run({"telegram_text_fallback_cards": [{"review_id": 1}]})

    assert answer_ctx["answer_hil_callback_result"]["ok"] is False
    assert photo_ctx["send_hil_telegram_photo_result"]["ok"] is False
    assert text_ctx["send_hil_telegram_text_fallback_result"]["ok"] is False


def test_edit_delete_and_log_nodes_ignore_non_dict_callback_data(monkeypatch):
    """Regression: non-dict finalized callback payload crashed on callback_data.get."""
    monkeypatch.setattr(edit_hil_message, "default_provider", _raise_default)
    monkeypatch.setattr(delete_hil_message, "default_provider", _raise_default)

    edit_ctx = edit_hil_message.run({"hil_finalized_callbacks": ["bad"]})
    delete_ctx = delete_hil_message.run({"message_edit_failed": True, "hil_finalized_callbacks": ["bad"]})
    edited_log_ctx = log_hil_message_edited.run({"hil_finalized_callbacks": ["bad"]})
    deleted_log_ctx = log_hil_message_deleted.run({"hil_finalized_callbacks": ["bad"]})

    assert edit_ctx["edit_hil_message_result"]["ok"] is False
    assert delete_ctx["delete_hil_message_result"]["ok"] is False
    assert edited_log_ctx["log_hil_message_edited_result"]["error"] == "Missing review_id"
    assert deleted_log_ctx["log_hil_message_deleted_result"]["error"] == "Missing review_id"


class _InsertProvider:
    def __init__(self):
        self.rows = []

    def insert_rows(self, *, schema, table, rows):
        self.rows.extend(rows)
        return [{"id": 7, **rows[0]}]


def test_supabase_message_loggers_build_event_rows():
    """Regression: logger adapter paths were untested and could drift from event schema."""
    provider = _InsertProvider()
    edited = log_hil_message_edited.SupabaseHilMessageEditLogger(provider).log_message_edited(
        "42", {"ok": True}
    )
    deleted = log_hil_message_deleted.SupabaseHilMessageDeleteLogger(provider).log_message_deleted(
        "42", {"ok": False, "error": "gone"}
    )

    assert edited["event_type"] == "message_edited"
    assert deleted["event_type"] == "message_deleted"
    assert provider.rows[1]["payload"]["error"] == "gone"


def test_item_wrapped_nodes_skip_polymorphic_inputs():
    """Regression: item wrappers with None/non-dict JSON crashed on .get."""
    assert browserbase_fetch.run({"thin_content_for_browserbase": [None]})["browserbase_results"] == []
    assert tavily_search_in_market.run({"tavily_queries": [None]}, provider=object())["tavily_search_results"] == []
    assert prepare_gemini_prompt.run({"stripped_content": [None]})["gemini_prompts"] == []
    assert strip_html.run({"browserbase_results": [None]})["stripped_content"] == []
    thin_ctx = if_tavily_content_thin.run({"picked_indian_listings": [{"json": {"tavily_content_len": "bad"}}]})
    assert len(thin_ctx["thin_content_for_browserbase"]) == 1


def test_search_providers_handle_non_dict_results():
    """Regression: provider results that were strings/lists crashed downstream search nodes."""

    class Browserbase:
        def fetch(self, *_, **__):
            return "html"

    class Tavily:
        def search(self, *_, **__):
            return {"ok": True, "results": ["bad"]}

    b_ctx = browserbase_fetch.run({"thin_content_for_browserbase": [{"json": {"tavily_url": "u"}}]}, provider=Browserbase())
    t_ctx = tavily_search_in_market.run({"tavily_queries": [{"json": {"tavily_query": "q"}}]}, provider=Tavily())

    assert b_ctx["browserbase_results"][0]["json"]["ok"] is False
    assert t_ctx["tavily_search_results"] == []


def test_gemini_extract_handles_non_dict_items_and_results():
    """Regression: non-dict Gemini items/results crashed on .get."""
    ctx = gemini_extract_product.run(
        {"gemini_prompts": [None, {"json": {"gemini_prompt": "prompt"}}]},
        gemini_fn=lambda _: "not-a-dict",
    )
    assert ctx["gemini_extracts"] == [{
        "json": {"gemini_prompt": "prompt", "ok": False, "gemini_status_code": 0, "error": "Gemini extraction failed"}
    }]


def _stub_auth():
    a = MagicMock(spec=llm.VertexAuth)
    a.get_token.return_value = "tkn"
    a.project_id = "p"
    a.location = "global"
    return a


def test_default_gemini_extract_tolerates_malformed_candidate(monkeypatch):
    """Regression: malformed Gemini candidate crashed on candidates[0].get."""
    response = MagicMock(spec=requests.Response)
    response.raise_for_status.return_value = None
    response.json.return_value = {"candidates": ["bad"]}
    monkeypatch.setattr(gemini_extract_product.requests, "post", lambda *_, **__: response)

    result = gemini_extract_product._default_gemini_extract("prompt", auth=_stub_auth())

    assert result["ok"] is True
    assert result["text"] == ""


def test_llm_providers_tolerate_malformed_candidate(monkeypatch):
    """Regression: malformed Gemini candidate crashed LLM provider parsing."""
    response = MagicMock(spec=requests.Response)
    response.raise_for_status.return_value = None
    response.json.return_value = {"candidates": ["bad"]}
    monkeypatch.setattr(llm.requests, "post", lambda *_, **__: response)

    assert llm.GeminiProvider(auth=_stub_auth()).generate("system", "user") == ""
    assert llm.GeminiAgentProvider(auth=_stub_auth()).call_with_tools("system", "user", []) == ""


def test_normalize_browserbase_uses_first_balanced_json_object():
    """Regression: greedy object regex spanned multiple Gemini JSON objects."""
    prompt = {
        "json": {
            "tavily_url": "https://example.com/product/1",
            "source_topic": "Wireless Earbuds",
            "tavily_title": "Wireless Earbuds",
            "tavily_raw_content": "Rs 999 in stock rating 4.5 stars",
            "tavily_domain": "shop.example",
        }
    }
    extract_text = (
        '{"product_name":"Wireless Earbuds","price_text":"Rs 999","image_urls":["https://img.example/a.jpg"],'
        '"is_product_page":true,"description":"nested {braces} ok"} {"product_name":"wrong"}'
    )
    ctx = normalize_browserbase_review.run({
        "gemini_prompts": [prompt],
        "gemini_extracts": [{"json": {"candidates": [{"content": {"parts": [{"text": extract_text}]}}]}}],
    })

    assert ctx["normalized_reviews"][0]["json"]["product_name"] == "Wireless Earbuds"


def test_pick_indian_listings_handles_bad_score_and_non_dict_items():
    """Regression: non-numeric Tavily scores and non-dict results crashed ranking."""
    result = {
        "json": {
            "tavily_query": "buy earbuds india",
            "source_topic": "Wireless Earbuds",
            "product_hint": "earbuds",
            "entity_hint": "Wireless Earbuds",
            "intent_mode": "direct_product",
            "tavily_url": "https://example.com/product/1",
            "tavily_title": "Wireless Earbuds",
            "tavily_raw_content": "Wireless Earbuds Rs 999 rating reviews",
            "tavily_score": "bad",
        }
    }
    ctx = pick_indian_listings.run({"tavily_search_results": [None, result]})

    assert len(ctx["picked_indian_listings"]) == 1


def test_pick_indian_listings_covers_preferred_fallback_and_merch_penalties():
    """Regression: ranking branches for preferred/fallback/merch paths were untested."""
    direct = {
        "json": {
            "tavily_query": "buy phone case india",
            "source_topic": "Phone Case",
            "product_hint": "phone case",
            "entity_hint": "",
            "intent_mode": "direct_product",
            "tavily_url": "https://example.com/product/1",
            "tavily_title": "Phone case cover",
            "tavily_raw_content": "Phone case cover Rs 299 rating reviews",
            "tavily_score": 0.9,
        }
    }
    fallback = {
        "json": {
            "tavily_query": "buy poster india",
            "source_topic": "Poster",
            "product_hint": "poster",
            "entity_hint": "",
            "intent_mode": "direct_product",
            "tavily_url": "https://example.com/page/2",
            "tavily_title": "Wall poster",
            "tavily_raw_content": "Wall poster Rs 199 rating reviews",
            "tavily_score": 0.9,
        }
    }
    merch_book = {
        "json": {
            "tavily_query": "buy marvel merchandise poster india",
            "source_topic": "Marvel",
            "product_hint": "poster",
            "entity_hint": "Marvel",
            "intent_mode": "merch",
            "tavily_url": "https://example.com/product/3",
            "tavily_title": "Marvel paperback book",
            "tavily_raw_content": "Marvel book Rs 499 reviews",
            "tavily_score": 0.9,
        }
    }
    ctx = pick_indian_listings.run({"tavily_search_results": [direct, fallback, merch_book]})

    assert len(ctx["picked_indian_listings"]) == 3


def test_pick_indian_listings_reaches_safe_preferred_and_fallback_modes():
    """Regression: safe-result loop was not covered for product/entity matches."""
    preferred = {
        "json": {
            "tavily_query": "buy p india",
            "source_topic": "p",
            "product_hint": "p",
            "entity_hint": "",
            "intent_mode": "direct_product",
            "tavily_url": "https://example.com/product/preferred",
            "tavily_title": "p",
            "tavily_raw_content": "p Rs 99 rating reviews",
            "tavily_score": 1.0,
        }
    }
    fallback = {
        "json": {
            "tavily_query": "buy q india",
            "source_topic": "q",
            "product_hint": "q",
            "entity_hint": "",
            "intent_mode": "direct_product",
            "tavily_url": "https://example.com/itemlist/q",
            "tavily_title": "q",
            "tavily_raw_content": "q Rs 99 rating reviews",
            "tavily_score": 1.0,
        }
    }
    ctx = pick_indian_listings.run({"tavily_search_results": [preferred, fallback]})

    modes = {item["json"]["tavily_selection_mode"] for item in ctx["picked_indian_listings"]}
    assert {"preferred", "fallback_safe"}.issubset(modes)


def test_pick_top_3_handles_malformed_response_shapes():
    """Regression: malformed CJ list response crashed nested .get and sort paths."""
    assert pick_top_3.pick_products({"data": "bad"}, {"keyword": "x"}) == []
    response = {"data": {"list": [
        {"pid": "1", "productNameEn": "Earbuds", "listedNum": "bad"},
        None,
        {"pid": "2", "productNameEn": "Earbuds Pro", "listedNum": 5},
    ]}}
    picked = pick_top_3.pick_products(response, {"keyword": "Earbuds"})
    assert [p["pid"] for p in picked] == ["2", "1"]
    assert pick_top_3.run({"cj_product_list_responses": [None]})["cj_top_products"] == []


def test_score_rank_skips_malformed_youtube_items():
    """Regression: malformed YouTube items crashed parse_youtube."""
    parsed = score_rank.parse_youtube([None, {"snippet": None}, {"snippet": {"title": "Topic", "tags": "bad"}}])
    # Fenix engine added velocity/search_volume to the per-item shape.
    assert parsed == [{"topic": "Topic", "source": "youtube_trending", "tags": [],
                       "velocity": None, "search_volume": None}]


def test_apply_supabase_store_adapter_methods():
    """Regression: Supabase HIL callback store adapter methods were unexercised."""
    from el.nodes import apply_hil_callback

    class Provider:
        def select_rows(self, **_):
            return [{"id": 1, "approval_status": "pending"}]

        def update_rows(self, **_):
            return [{"id": 1, "approval_status": "approved"}]

        def insert_rows(self, **kwargs):
            return kwargs["rows"]

    store = apply_hil_callback.SupabaseHilCallbackStore(Provider())
    assert store.find_review(1, "tok")["id"] == 1
    assert store.update_pending_review(1, "tok", {"approval_status": "approved"})["approval_status"] == "approved"
    assert store.insert_event({"review_id": 1})["review_id"] == 1
    assert apply_hil_callback._to_int_or_none("bad") is None


def test_build_tavily_query_handles_long_noisy_topics_and_polymorphic_items():
    """Regression: odd ranked items crashed query construction or produced empty keywords."""
    long_topic = "Official Video Song " + " ".join(f"word{i}" for i in range(20)) + "| trailer"
    ctx = {
        "ranked_payload": [
            None,
            {"json": {"search_query_in": "", "topic": long_topic, "suggested_product_type": "phone case"}},
            {"json": {"search_query_in": "x", "topic": "Marvel movie", "suggested_product_type": ""}},
        ]
    }
    build_tavily_query.run(ctx)

    assert len(ctx["tavily_queries"]) == 2
    assert ctx["tavily_queries"][0]["json"]["keyword"]
    assert ctx["tavily_queries"][1]["json"]["product_hint"] == "x"


def test_build_tavily_query_empty_and_fallback_query_branches():
    """Regression: empty entity/product paths must skip or build fallback queries."""
    ctx = {
        "ranked_payload": [
            {"json": {"search_query_in": "", "topic": "", "suggested_product_type": ""}},
            {"json": {"search_query_in": "", "topic": "Marvel movie", "suggested_product_type": ""}},
            {"json": {"search_query_in": "desk organizer", "topic": "", "suggested_product_type": ""}},
            {"json": {"search_query_in": "", "topic": "plain topic", "suggested_product_type": ""}},
        ]
    }
    build_tavily_query.run(ctx)

    assert len(ctx["tavily_queries"]) == 3
    assert ctx["tavily_queries"][0]["json"]["product_hint"] == "t shirt"
    assert ctx["tavily_queries"][1]["json"]["tavily_query"].startswith("buy")
    assert ctx["tavily_queries"][2]["json"]["tavily_query"] == "buy plain topic india"


def test_cj_token_default_provider_failure_and_bad_data(monkeypatch):
    """Regression: CJ provider creation and bad data shape escaped fail-soft path."""
    from el.nodes import cj_get_token

    monkeypatch.setattr(cj_get_token.cj, "default_provider", _raise_default)
    ctx = cj_get_token.run({})
    assert ctx["cj_get_token_result"]["ok"] is False

    class BadProvider:
        def get_access_token(self):
            return {"data": "bad"}

    ctx = cj_get_token.run({}, provider=BadProvider())
    assert ctx["cj_get_token_result"]["ok"] is False


def test_valid_edit_delete_default_provider_failure_is_soft(monkeypatch):
    """Regression: Telegram edit/delete provider creation failures raised with valid callbacks."""
    monkeypatch.setattr(edit_hil_message, "default_provider", _raise_default)
    monkeypatch.setattr(delete_hil_message, "default_provider", _raise_default)
    callback = {"chat_id": "1", "message_id": "2", "telegram_edit_text": "done"}

    edit_ctx = edit_hil_message.run({"hil_finalized_callbacks": callback})
    delete_ctx = delete_hil_message.run({"message_edit_failed": True, "hil_finalized_callbacks": callback})

    assert edit_ctx["edit_hil_message_result"]["error"] == "missing credentials"
    assert delete_ctx["delete_hil_message_result"]["error"] == "missing credentials"


def test_requests_image_download_provider_success(monkeypatch):
    """Regression: real image downloader response mapping had no coverage."""
    from el.nodes import download_product_image

    response = MagicMock(spec=requests.Response)
    response.headers = {"Content-Type": "image/png; charset=binary"}
    response.content = b"png"
    response.raise_for_status.return_value = None

    class Session:
        max_redirects = 0

        def get(self, *_, **__):
            return response

    monkeypatch.setattr(download_product_image.requests, "Session", Session)
    provider = download_product_image.RequestsImageDownloadProvider()

    result = provider.download("https://img.example/a", file_name="a")

    assert result["data"] == b"png"
    assert result["mimeType"] == "image/png"


def test_gemini_default_extract_error_paths(monkeypatch):
    """Regression: Gemini HTTP/JSON errors must return ok=false."""

    def request_error(*_, **__):
        raise requests.RequestException("down")

    monkeypatch.setattr(gemini_extract_product.requests, "post", request_error)
    assert gemini_extract_product._default_gemini_extract("prompt", auth=_stub_auth())["ok"] is False

    response = MagicMock(spec=requests.Response)
    response.raise_for_status.return_value = None
    response.json.side_effect = ValueError("html")
    monkeypatch.setattr(gemini_extract_product.requests, "post", lambda *_, **__: response)
    assert gemini_extract_product._default_gemini_extract("prompt", auth=_stub_auth())["ok"] is False


def test_tavily_search_node_error_and_empty_result_paths():
    """Regression: Tavily non-ok and empty result payloads need soft outputs."""

    class NonOk:
        def search(self, *_, **__):
            return {"ok": False, "error": "api"}

    class Empty:
        def search(self, *_, **__):
            return {"ok": True, "results": []}

    query = {"json": {"tavily_query": "q"}}
    non_ok = tavily_search_in_market.run({"tavily_queries": [query]}, provider=NonOk())
    empty = tavily_search_in_market.run({"tavily_queries": [query]}, provider=Empty())

    assert non_ok["tavily_search_results"][0]["json"]["error"] == "api"
    assert empty["tavily_search_results"] == []


def test_telegram_alert_default_provider_failure(monkeypatch):
    """Regression: alert node provider construction failure crashed the error path."""

    class FailingBot:
        def __init__(self):
            raise RuntimeError("no bot")

    monkeypatch.setattr(telegram_alert, "TelegramBotProvider", FailingBot)
    ctx = telegram_alert.run({"formatted_error": [{"text": "boom"}]})
    assert ctx["telegram_alert_result"]["ok"] is False
    assert ctx["telegram_alert_result"]["error"] == "no bot"


def test_update_bcc_handles_non_numeric_current_values_and_cold_start():
    """Regression: malformed BCC posterior rows crashed numeric update."""

    class Provider:
        def __init__(self, rows):
            self.rows = rows
            self.upserts = []

        def select_rows(self, **_):
            return self.rows

        def upsert_rows(self, **kwargs):
            self.upserts.append(kwargs)
            return kwargs["rows"]

    bad = Provider([{"category": "X", "alpha": "bad", "beta": "bad"}])
    cold = Provider([])
    update_bcc_posterior.run({"hil_callback_decision": {"decision": "approved", "category": "X"}}, provider=bad)
    update_bcc_posterior.run({"hil_callback_decision": {"decision": "rejected", "category": "Y"}}, provider=cold)

    assert bad.upserts[0]["rows"][0] == {"category": "X", "alpha": 2.0, "beta": 1.0}
    assert cold.upserts[0]["rows"][0] == {"category": "Y", "alpha": 1, "beta": 2}


def test_normalize_browserbase_exercises_filter_and_fallback_branches():
    """Regression: malformed Gemini/page variants crashed Browserbase normalization."""
    prompts = [
        {"json": {"tavily_url": "https://shop.example/search?q=x", "source_topic": "x"}},
        {"json": {
            "tavily_url": "https://shop.example/products/1",
            "source_topic": "Wireless Earbuds",
            "tavily_title": "Amazon.in: Buy Wireless Earbuds Online at Low Prices in India : Amazon.in",
            "tavily_raw_content": "Wireless Earbuds in stock Rs 999 4.5/5 123 reviews https://img.example/a.jpg",
            "tavily_domain": "shop.example",
        }},
        {"json": {
            "tavily_url": "https://shop.example/products/2",
            "source_topic": "Movie Trailer",
            "tavily_title": "Novel paperback",
            "tavily_query": "movie t shirt",
            "tavily_raw_content": "Novel paperback Rs 99 https://img.example/b.gif",
        }},
        {"json": {
            "tavily_url": "https://shop.example/products/3",
            "source_topic": "Cheap item",
            "tavily_title": "Cheap item",
            "tavily_raw_content": "Rs 10 https://img.example/c.jpg",
        }},
    ]
    extracts = [
        {"json": {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}},
        {"json": {"candidates": [{"content": {"parts": [{"text": "not json then {bad"}]}}]}},
        {"json": {"candidates": [{"content": {"parts": [{"text": '{"product_name":"Novel paperback","image_urls":"https://img.example/b.gif","is_product_page":true}'}]}}]}},
        {"json": {"candidates": [{"content": {"parts": [{"text": '{"product_name":"Cheap item","price_text":"Rs 10","image_urls":"[\\"https://img.example/c.jpg\\"]","is_product_page":true}'}]}}]}},
    ]

    ctx = normalize_browserbase_review.run({"gemini_prompts": prompts, "gemini_extracts": extracts})

    assert len(ctx["normalized_reviews"]) == 1
    row = ctx["normalized_reviews"][0]["json"]
    assert row["product_name"] == "Wireless Earbuds"
    assert row["availability_status"] == "in_stock"
