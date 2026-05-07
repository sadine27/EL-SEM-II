"""Tests for el/nodes/drive_upload_scraped.py."""
from __future__ import annotations

import base64

from el import google_drive
from el.nodes import drive_upload_scraped as dus


class FakeDriveProvider:
    def __init__(self, should_error: bool = False):
        self.should_error = should_error
        self.uploaded = None

    def upload_file(self, filename, content, mime_type, folder_id=google_drive.DEFAULT_FOLDER_ID):
        self.uploaded = {"filename": filename, "size": len(content), "folder_id": folder_id}
        if self.should_error:
            raise Exception("Drive API error")
        return {"id": "drive-file-id", "name": filename}


def _file_item(content: str = '{"hello":"world"}', filename: str = "test.json") -> dict:
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    return {
        "json": {"filename": filename},
        "binary": {"data": {"data": encoded, "mimeType": "application/json", "fileName": filename}},
    }


def test_uploads_to_scraped_folder_by_default():
    provider = FakeDriveProvider()
    ctx = {"scraped_json_file": _file_item()}
    dus.run(ctx, provider=provider)
    assert ctx["scraped_drive_upload_result"]["ok"] is True
    assert ctx["scraped_drive_upload_result"]["folder_id"] == google_drive.SCRAPED_FOLDER_ID
    assert provider.uploaded["folder_id"] == google_drive.SCRAPED_FOLDER_ID


def test_no_file_short_circuits():
    provider = FakeDriveProvider()
    ctx = {}
    dus.run(ctx, provider=provider)
    assert ctx["scraped_drive_upload_result"]["uploaded"] is False
    assert provider.uploaded is None


def test_provider_error_soft_fail():
    provider = FakeDriveProvider(should_error=True)
    ctx = {"scraped_json_file": _file_item()}
    dus.run(ctx, provider=provider)
    assert ctx["scraped_drive_upload_result"]["ok"] is False


def test_respects_custom_folder_id_in_ctx():
    provider = FakeDriveProvider()
    ctx = {"scraped_json_file": _file_item(), "scraped_drive_folder_id": "custom-folder"}
    dus.run(ctx, provider=provider)
    assert provider.uploaded["folder_id"] == "custom-folder"
