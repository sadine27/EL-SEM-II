"""Tests for el/nodes/drive_upload.py."""
from __future__ import annotations

from el import google_drive
from el.nodes import drive_upload
from el.nodes import prepare_json_file


class FakeProvider:
    def __init__(self, response: dict | None = None, error: Exception | None = None):
        self.response = response or {"id": "FILEID", "name": "trending.json"}
        self.error = error
        self.calls: list[tuple[str, bytes, str, str]] = []

    def upload_file(
        self,
        filename: str,
        content: bytes,
        mime_type: str,
        folder_id: str = google_drive.DEFAULT_FOLDER_ID,
    ) -> dict:
        self.calls.append((filename, content, mime_type, folder_id))
        if self.error:
            raise self.error
        return self.response


def test_drive_upload_uploads_prepared_json_file():
    file_item = prepare_json_file.build_file_item({"hello": "world"}, "trend.json")
    provider = FakeProvider({"id": "123", "name": "trend.json"})
    ctx = drive_upload.run({"json_file": file_item}, provider=provider)
    assert provider.calls == [
        ("trend.json", b'{\n  "hello": "world"\n}', "application/json",
         google_drive.DEFAULT_FOLDER_ID)
    ]
    assert ctx["drive_upload_result"] == {
        "ok": True,
        "uploaded": True,
        "filename": "trend.json",
        "folder_id": google_drive.DEFAULT_FOLDER_ID,
        "response": {"id": "123", "name": "trend.json"},
    }


def test_drive_upload_honors_ctx_folder_override():
    file_item = prepare_json_file.build_file_item({}, "trend.json")
    provider = FakeProvider()
    drive_upload.run({"json_file": file_item, "drive_folder_id": "OTHER"}, provider=provider)
    assert provider.calls[0][3] == "OTHER"


def test_drive_upload_skips_without_json_file():
    provider = FakeProvider()
    ctx = drive_upload.run({}, provider=provider)
    assert provider.calls == []
    assert ctx["drive_upload_result"] == {"ok": True, "uploaded": False}


def test_drive_upload_continue_on_provider_fail():
    file_item = prepare_json_file.build_file_item({}, "trend.json")
    ctx = drive_upload.run({"json_file": file_item},
                           provider=FakeProvider(error=RuntimeError("quota")))
    assert ctx["drive_upload_result"] == {
        "ok": False,
        "uploaded": False,
        "folder_id": google_drive.DEFAULT_FOLDER_ID,
        "error": "quota",
    }


def test_drive_upload_continue_on_bad_file_shape():
    ctx = drive_upload.run({"json_file": {"json": {"filename": "x.json"}}},
                           provider=FakeProvider())
    assert ctx["drive_upload_result"] == {
        "ok": False,
        "uploaded": False,
        "folder_id": google_drive.DEFAULT_FOLDER_ID,
        "error": "json_file is missing binary.data.data",
    }
