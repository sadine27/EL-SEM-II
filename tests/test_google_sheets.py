"""Tests for el/google_sheets.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from el import google_sheets


def _fake_response(json_payload: dict, ok: bool = True, status_code: int = 200):
    resp = MagicMock(spec=requests.Response)
    resp.ok = ok
    resp.status_code = status_code
    resp.json.return_value = json_payload
    if not ok:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Error")
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_quote_sheet_title_escapes_single_quotes():
    assert google_sheets._quote_sheet_title("Bob's") == "'Bob''s'"


def test_column_letter_handles_multi_letter_columns():
    assert google_sheets._column_letter(1) == "A"
    assert google_sheets._column_letter(8) == "H"
    assert google_sheets._column_letter(27) == "AA"


def test_google_sheets_provider_create_sheet_request_shape():
    provider = google_sheets.GoogleSheetsProvider(
        spreadsheet_id="SHEETID",
        service_account_info={"client_email": "x", "private_key": "y"},
    )
    with patch.object(provider, "_access_token", return_value="TOKEN"), \
            patch.object(google_sheets.requests, "post") as mock_post:
        mock_post.return_value = _fake_response({"replies": []})
        out = provider.create_sheet("2026-05-07")
    assert out == {"replies": []}
    url, = mock_post.call_args.args
    kwargs = mock_post.call_args.kwargs
    assert url == f"{google_sheets.SHEETS_API_BASE}/SHEETID:batchUpdate"
    assert kwargs["headers"]["Authorization"] == "Bearer TOKEN"
    assert kwargs["json"] == {
        "requests": [{"addSheet": {"properties": {"title": "2026-05-07"}}}]
    }


def test_google_sheets_provider_append_rows_request_shape():
    provider = google_sheets.GoogleSheetsProvider(
        spreadsheet_id="SHEETID",
        service_account_info={"client_email": "x", "private_key": "y"},
    )
    rows = [{"run_date": "2026-05-07", "rank": 1, "topic": "Earbuds"}]
    columns = ("run_date", "rank", "topic")
    with patch.object(provider, "_access_token", return_value="TOKEN"), \
            patch.object(google_sheets.requests, "post") as mock_post:
        mock_post.return_value = _fake_response({"updates": {"updatedRows": 1}})
        out = provider.append_rows("2026-05-07", rows, columns)
    assert out == {"updates": {"updatedRows": 1}}
    url, = mock_post.call_args.args
    kwargs = mock_post.call_args.kwargs
    assert url == (
        f"{google_sheets.SHEETS_API_BASE}/SHEETID/values/"
        "'2026-05-07'!A:C:append"
    )
    assert kwargs["params"] == {
        "valueInputOption": "RAW",
        "insertDataOption": "INSERT_ROWS",
    }
    assert kwargs["json"] == {
        "majorDimension": "ROWS",
        "values": [["2026-05-07", 1, "Earbuds"]],
    }


def test_google_sheets_provider_propagates_http_error():
    provider = google_sheets.GoogleSheetsProvider(
        spreadsheet_id="SHEETID",
        service_account_info={"client_email": "x", "private_key": "y"},
    )
    with patch.object(provider, "_access_token", return_value="TOKEN"), \
            patch.object(google_sheets.requests, "post") as mock_post:
        mock_post.return_value = _fake_response({}, ok=False, status_code=403)
        with pytest.raises(requests.HTTPError):
            provider.create_sheet("2026-05-07")
