"""Minimal Supabase REST helper for EL storage nodes."""
from __future__ import annotations

from urllib.parse import urljoin

import requests

from el import config

HIL_REVIEWS_TABLE = "hil_reviews"
HIL_REVIEW_EVENTS_TABLE = "hil_review_events"
HIL_REVIEWS_SCHEMA = "private"
HIL_LOGGING_EVENTS_TABLE = "hil_logging_events"
PRODUCT_EMBEDDINGS_TABLE = "product_embeddings"
PRODUCT_EMBEDDINGS_CONFLICT_COLUMNS = ("product_key",)
MATCH_PRODUCT_EMBEDDINGS_FN = "match_product_embeddings"
RUN_REQUESTS_TABLE = "run_requests"
RUN_REQUESTS_SCHEMA = "private"
HIL_REVIEWS_CONFLICT_COLUMNS = (
    "workflow_run_id",
    "source_provider",
    "source_topic",
    "product_url",
)


class SupabaseRestProvider:
    def __init__(self, url: str | None = None, key: str | None = None, timeout: int = 30):
        self.url = (url or config.require("SUPABASE_URL")).rstrip("/") + "/"
        self.key = (
            key
            or config.get("SUPABASE_SERVICE_ROLE_KEY")
            or config.get("SUPABASE_SECRET_KEY")
            or config.require("SUPABASE_KEY")
        )
        self.timeout = timeout

    def upsert_rows(
        self,
        *,
        schema: str,
        table: str,
        rows: list[dict],
        conflict_columns: tuple[str, ...],
    ) -> list[dict]:
        endpoint = urljoin(self.url, f"rest/v1/{table}")
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Profile": schema,
            "Content-Profile": schema,
            "Prefer": "resolution=merge-duplicates,return=representation",
        }
        resp = requests.post(
            endpoint,
            headers=headers,
            params={"on_conflict": ",".join(conflict_columns)},
            json=rows,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else [data]

    def update_row_by_id(
        self,
        *,
        schema: str,
        table: str,
        row_id: int | str,
        updates: dict,
    ) -> list[dict]:
        endpoint = urljoin(self.url, f"rest/v1/{table}")
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Profile": schema,
            "Content-Profile": schema,
            "Prefer": "return=representation",
        }
        resp = requests.patch(
            endpoint,
            headers=headers,
            params={"id": f"eq.{row_id}"},
            json=updates,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else [data]

    def select_rows(
        self,
        *,
        schema: str,
        table: str,
        filters: dict[str, str],
        select: str = "*",
        limit: int | None = None,
    ) -> list[dict]:
        endpoint = urljoin(self.url, f"rest/v1/{table}")
        params = {"select": select, **filters}
        if limit is not None:
            params["limit"] = str(limit)
        resp = requests.get(
            endpoint,
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Accept": "application/json",
                "Accept-Profile": schema,
            },
            params=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else [data]

    def insert_rows(
        self,
        *,
        schema: str,
        table: str,
        rows: list[dict],
    ) -> list[dict]:
        endpoint = urljoin(self.url, f"rest/v1/{table}")
        resp = requests.post(
            endpoint,
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Accept-Profile": schema,
                "Content-Profile": schema,
                "Prefer": "return=representation",
            },
            json=rows,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else [data]

    def call_rpc(
        self,
        *,
        schema: str,
        function: str,
        params: dict,
    ) -> list[dict]:
        """Invoke a Postgres function via PostgREST's /rpc/ endpoint."""
        endpoint = urljoin(self.url, f"rest/v1/rpc/{function}")
        resp = requests.post(
            endpoint,
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Accept-Profile": schema,
                "Content-Profile": schema,
            },
            json=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        if data is None:
            return []
        return [data]

    def update_rows(
        self,
        *,
        schema: str,
        table: str,
        filters: dict[str, str],
        updates: dict,
    ) -> list[dict]:
        endpoint = urljoin(self.url, f"rest/v1/{table}")
        resp = requests.patch(
            endpoint,
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Accept-Profile": schema,
                "Content-Profile": schema,
                "Prefer": "return=representation",
            },
            params=filters,
            json=updates,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else [data]
