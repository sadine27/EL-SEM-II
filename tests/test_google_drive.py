"""Tests for el/google_drive.py."""
from __future__ import annotations

import json
import re
from unittest.mock import MagicMock, patch

import pytest
import requests

from el import google_drive


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


def test_multipart_related_contains_metadata_and_content():
    body, content_type = google_drive._multipart_related(
        {"name": "trending.json", "parents": ["FOLDER"]},
        b'{"ok":true}',
        "application/json",
    )
    boundary = re.search(r"boundary=(.+)$", content_type).group(1)
    assert content_type.startswith("multipart/related; boundary=")
    assert body.startswith(f"--{boundary}\r\n".encode("utf-8"))
    assert b"Content-Type: application/json; charset=UTF-8" in body
    assert json.dumps({"name": "trending.json", "parents": ["FOLDER"]},
                      separators=(",", ":")).encode("utf-8") in body
    assert b"Content-Type: application/json\r\n\r\n" in body
    assert b'{"ok":true}' in body
    assert body.endswith(f"\r\n--{boundary}--\r\n".encode("utf-8"))


def test_google_drive_provider_upload_file_request_shape():
    provider = google_drive.GoogleDriveProvider(
        service_account_info={"client_email": "x", "private_key": "y"},
    )
    with patch.object(provider, "_access_token", return_value="TOKEN"), \
            patch.object(google_drive.requests, "post") as mock_post:
        mock_post.return_value = _fake_response({"id": "FILEID", "name": "x.json"})
        out = provider.upload_file("x.json", b"{}", "application/json", folder_id="FOLDER")

    assert out == {"id": "FILEID", "name": "x.json"}
    url, = mock_post.call_args.args
    kwargs = mock_post.call_args.kwargs
    assert url == google_drive.DRIVE_UPLOAD_URL
    assert kwargs["headers"]["Authorization"] == "Bearer TOKEN"
    assert kwargs["headers"]["Content-Type"].startswith("multipart/related; boundary=")
    assert kwargs["params"] == {
        "uploadType": "multipart",
        "fields": "id,name,mimeType,parents,webViewLink",
    }
    assert kwargs["timeout"] == google_drive.DEFAULT_TIMEOUT
    assert b'"name":"x.json"' in kwargs["data"]
    assert b'"parents":["FOLDER"]' in kwargs["data"]
    assert b"{}" in kwargs["data"]


def test_google_drive_provider_propagates_http_error():
    provider = google_drive.GoogleDriveProvider(
        service_account_info={"client_email": "x", "private_key": "y"},
    )
    with patch.object(provider, "_access_token", return_value="TOKEN"), \
            patch.object(google_drive.requests, "post") as mock_post:
        mock_post.return_value = _fake_response({}, ok=False, status_code=403)
        with pytest.raises(requests.HTTPError):
            provider.upload_file("x.json", b"{}", "application/json")
