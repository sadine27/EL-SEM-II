"""Minimal Google Sheets API client for the ported storage nodes."""
from __future__ import annotations

import json
from typing import Protocol, Sequence

import requests

from el import config

SPREADSHEET_ID = "1WVIWkLHZkNw4mqUQwnUy0j2k_5eogREcCfPySzRLn2A"
SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)
DEFAULT_TIMEOUT = 30


class SheetsProvider(Protocol):
    def create_sheet(self, title: str) -> dict:
        ...

    def append_rows(self, title: str, rows: list[dict], columns: Sequence[str]) -> dict:
        ...


class GoogleSheetsProvider:
    def __init__(
        self,
        spreadsheet_id: str = SPREADSHEET_ID,
        service_account_info: dict | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.spreadsheet_id = spreadsheet_id
        self.service_account_info = service_account_info or _load_service_account_info()
        self.timeout = timeout

    def create_sheet(self, title: str) -> dict:
        url = f"{SHEETS_API_BASE}/{self.spreadsheet_id}:batchUpdate"
        body = {"requests": [{"addSheet": {"properties": {"title": title}}}]}
        resp = requests.post(
            url,
            headers=self._headers(),
            json=body,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def append_rows(self, title: str, rows: list[dict], columns: Sequence[str]) -> dict:
        values = [[row.get(col, "") for col in columns] for row in rows]
        range_name = f"{_quote_sheet_title(title)}!A:{_column_letter(len(columns))}"
        url = f"{SHEETS_API_BASE}/{self.spreadsheet_id}/values/{range_name}:append"
        resp = requests.post(
            url,
            headers=self._headers(),
            params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
            json={"majorDimension": "ROWS", "values": values},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token()}",
            "Content-Type": "application/json",
        }

    def _access_token(self) -> str:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account
        except ImportError as exc:  # pragma: no cover - depends on local install
            raise RuntimeError("Install google-auth to use Google Sheets storage") from exc

        creds = service_account.Credentials.from_service_account_info(
            self.service_account_info,
            scopes=list(SCOPES),
        )
        creds.refresh(Request())
        return creds.token


def _load_service_account_info() -> dict:
    raw = config.require("GOOGLE_SERVICE_ACCOUNT_JSON")
    return json.loads(raw)


def _quote_sheet_title(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def _column_letter(index: int) -> str:
    letters = ""
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def default_provider() -> SheetsProvider:
    return GoogleSheetsProvider()
