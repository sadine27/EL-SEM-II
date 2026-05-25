"""Minimal Google Drive API client for archive upload nodes."""
from __future__ import annotations

import json
import uuid
from typing import Protocol

import requests

from el import config

DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
DRIVE_EXPORT_URL = "https://www.googleapis.com/drive/v3/files/{file_id}/export"
DEFAULT_FOLDER_ID = "1M0FRJeZ6uguJSfmheWwU8hwiZe_tjVja"
SCRAPED_FOLDER_ID = "1jihlrDk1iKxGO7v4VChrEhPphaBPfvhx"
XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SCOPES = ("https://www.googleapis.com/auth/drive.file",)
DEFAULT_TIMEOUT = 30


class DriveProvider(Protocol):
    def upload_file(
        self,
        filename: str,
        content: bytes,
        mime_type: str,
        folder_id: str = DEFAULT_FOLDER_ID,
    ) -> dict:
        ...

    def export_file(self, file_id: str, mime_type: str) -> bytes:
        ...


class GoogleDriveProvider:
    def __init__(
        self,
        service_account_info: dict | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.service_account_info = service_account_info or _load_service_account_info()
        self.timeout = timeout

    def upload_file(
        self,
        filename: str,
        content: bytes,
        mime_type: str,
        folder_id: str = DEFAULT_FOLDER_ID,
    ) -> dict:
        metadata = {"name": filename, "parents": [folder_id]}
        body, content_type = _multipart_related(metadata, content, mime_type)
        resp = requests.post(
            DRIVE_UPLOAD_URL,
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "Content-Type": content_type,
            },
            params={
                "uploadType": "multipart",
                "fields": "id,name,mimeType,parents,webViewLink",
                "supportsAllDrives": "true",
            },
            data=body,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def export_file(self, file_id: str, mime_type: str = XLSX_MIME_TYPE) -> bytes:
        """Export a Google-native file (Sheet/Doc/Slide) as the given MIME type.

        For Google Sheets, mime_type defaults to XLSX. Returns raw file bytes.
        """
        resp = requests.get(
            DRIVE_EXPORT_URL.format(file_id=file_id),
            headers={"Authorization": f"Bearer {self._access_token()}"},
            params={"mimeType": mime_type},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.content

    def _access_token(self) -> str:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account
        except ImportError as exc:  # pragma: no cover - depends on local install
            raise RuntimeError("Install google-auth to use Google Drive storage") from exc

        creds = service_account.Credentials.from_service_account_info(
            self.service_account_info,
            scopes=list(SCOPES),
        )
        creds.refresh(Request())
        return creds.token


def _load_service_account_info() -> dict:
    raw = config.require("GOOGLE_SERVICE_ACCOUNT_JSON")
    return json.loads(raw)


def _multipart_related(metadata: dict, content: bytes, mime_type: str) -> tuple[bytes, str]:
    boundary = f"===============el_{uuid.uuid4().hex}=="
    metadata_json = json.dumps(metadata, separators=(",", ":"))
    parts = [
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{metadata_json}\r\n",
        f"--{boundary}\r\n"
        f"Content-Type: {mime_type}\r\n\r\n",
    ]
    body = "".join(parts).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return body, f"multipart/related; boundary={boundary}"


def default_provider() -> DriveProvider:
    return GoogleDriveProvider()
