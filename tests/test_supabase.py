"""Tests for el/supabase.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from el import supabase


def _response(data=None, status_code=200):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = data if data is not None else [{"id": 1}]
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Error")
    return resp


def test_supabase_rest_provider_upsert_rows_request_shape():
    provider = supabase.SupabaseRestProvider(
        url="https://example.supabase.co",
        key="service-key",
    )

    with patch.object(supabase.requests, "post", return_value=_response([{"id": 1}])) as mock_post:
        data = provider.upsert_rows(
            schema="private",
            table="hil_reviews",
            rows=[{"workflow_run_id": "run-1"}],
            conflict_columns=("workflow_run_id", "source_provider"),
        )

    assert data == [{"id": 1}]
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert mock_post.call_args.args[0] == "https://example.supabase.co/rest/v1/hil_reviews"
    assert kwargs["headers"]["apikey"] == "service-key"
    assert kwargs["headers"]["Authorization"] == "Bearer service-key"
    assert kwargs["headers"]["Accept-Profile"] == "private"
    assert kwargs["headers"]["Content-Profile"] == "private"
    assert kwargs["headers"]["Prefer"] == "resolution=merge-duplicates,return=representation"
    assert kwargs["params"] == {"on_conflict": "workflow_run_id,source_provider"}
    assert kwargs["json"] == [{"workflow_run_id": "run-1"}]


def test_supabase_rest_provider_wraps_non_list_response():
    provider = supabase.SupabaseRestProvider(
        url="https://example.supabase.co",
        key="service-key",
    )

    with patch.object(supabase.requests, "post", return_value=_response({"id": 1})):
        data = provider.upsert_rows(
            schema="private",
            table="hil_reviews",
            rows=[{"workflow_run_id": "run-1"}],
            conflict_columns=("workflow_run_id",),
        )

    assert data == [{"id": 1}]


def test_supabase_rest_provider_propagates_http_error():
    provider = supabase.SupabaseRestProvider(
        url="https://example.supabase.co",
        key="service-key",
    )

    with patch.object(supabase.requests, "post", return_value=_response(status_code=500)):
        try:
            provider.upsert_rows(
                schema="private",
                table="hil_reviews",
                rows=[{"workflow_run_id": "run-1"}],
                conflict_columns=("workflow_run_id",),
            )
        except requests.HTTPError:
            pass
        else:
            raise AssertionError("Expected HTTPError")


def test_supabase_rest_provider_update_row_by_id_request_shape():
    provider = supabase.SupabaseRestProvider(
        url="https://example.supabase.co",
        key="service-key",
    )

    with patch.object(supabase.requests, "patch", return_value=_response([{"id": 42}])) as mock_patch:
        data = provider.update_row_by_id(
            schema="private",
            table="hil_reviews",
            row_id=42,
            updates={"telegram_media_status": "sent"},
        )

    assert data == [{"id": 42}]
    mock_patch.assert_called_once()
    _, kwargs = mock_patch.call_args
    assert mock_patch.call_args.args[0] == "https://example.supabase.co/rest/v1/hil_reviews"
    assert kwargs["headers"]["apikey"] == "service-key"
    assert kwargs["headers"]["Authorization"] == "Bearer service-key"
    assert kwargs["headers"]["Accept-Profile"] == "private"
    assert kwargs["headers"]["Content-Profile"] == "private"
    assert kwargs["headers"]["Prefer"] == "return=representation"
    assert kwargs["params"] == {"id": "eq.42"}
    assert kwargs["json"] == {"telegram_media_status": "sent"}


def test_supabase_rest_provider_select_rows_request_shape():
    provider = supabase.SupabaseRestProvider(
        url="https://example.supabase.co",
        key="service-key",
    )

    with patch.object(supabase.requests, "get", return_value=_response([{"id": 42}])) as mock_get:
        data = provider.select_rows(
            schema="private",
            table="hil_reviews",
            filters={"id": "eq.42"},
            limit=1,
        )

    assert data == [{"id": 42}]
    assert mock_get.call_args.args[0] == "https://example.supabase.co/rest/v1/hil_reviews"
    _, kwargs = mock_get.call_args
    assert kwargs["headers"]["Accept-Profile"] == "private"
    assert kwargs["params"] == {"select": "*", "id": "eq.42", "limit": "1"}


def test_supabase_rest_provider_insert_rows_request_shape():
    provider = supabase.SupabaseRestProvider(
        url="https://example.supabase.co",
        key="service-key",
    )

    with patch.object(supabase.requests, "post", return_value=_response([{"id": 7}])) as mock_post:
        data = provider.insert_rows(
            schema="private",
            table="hil_review_events",
            rows=[{"event_type": "callback_received"}],
        )

    assert data == [{"id": 7}]
    assert mock_post.call_args.args[0] == "https://example.supabase.co/rest/v1/hil_review_events"
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["Prefer"] == "return=representation"
    assert kwargs["json"] == [{"event_type": "callback_received"}]


def test_supabase_rest_provider_update_rows_request_shape():
    provider = supabase.SupabaseRestProvider(
        url="https://example.supabase.co",
        key="service-key",
    )

    with patch.object(supabase.requests, "patch", return_value=_response([{"id": 42}])) as mock_patch:
        data = provider.update_rows(
            schema="private",
            table="hil_reviews",
            filters={"id": "eq.42", "approval_status": "eq.pending"},
            updates={"approval_status": "approved"},
        )

    assert data == [{"id": 42}]
    assert mock_patch.call_args.args[0] == "https://example.supabase.co/rest/v1/hil_reviews"
    _, kwargs = mock_patch.call_args
    assert kwargs["params"] == {"id": "eq.42", "approval_status": "eq.pending"}
    assert kwargs["json"] == {"approval_status": "approved"}
