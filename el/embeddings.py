"""Vertex multimodal embedding client.

Provides text + image embeddings for SP3's product-similarity feature.
Reuses the OAuth flow from el/llm.py (VertexAuth) so no new credentials
are required.

Models (overridable via env):
  text:  text-embedding-005           → 768-dim
  image: multimodalembedding@001      → 1408-dim

Wire-format references:
  https://cloud.google.com/vertex-ai/generative-ai/docs/embeddings/get-text-embeddings
  https://cloud.google.com/vertex-ai/generative-ai/docs/embeddings/get-multimodal-embeddings
"""
from __future__ import annotations

import base64
import hashlib
import time
from typing import Protocol, runtime_checkable

import requests

from el import config
from el.llm import VertexAuth, default_vertex_auth
from el.logger import get_logger

log = get_logger(__name__)

DEFAULT_TEXT_MODEL = "text-embedding-005"
DEFAULT_IMAGE_MODEL = "multimodalembedding@001"
DEFAULT_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 3
RETRY_STATUS = {429, 500, 502, 503, 504}

TEXT_DIM = 768
IMAGE_DIM = 1408


class EmbeddingError(Exception):
    """Raised when an embedding call fails permanently (after all retries)."""


@runtime_checkable
class EmbeddingProvider(Protocol):
    def embed_text(self, text: str) -> list[float]: ...
    def embed_image(self, image_url: str) -> list[float]: ...


def _vertex_predict_url(auth: VertexAuth, model: str) -> str:
    host = (
        "https://aiplatform.googleapis.com"
        if auth.location == "global"
        else f"https://{auth.location}-aiplatform.googleapis.com"
    )
    return (
        f"{host}/v1/projects/{auth.project_id}/locations/{auth.location}"
        f"/publishers/google/models/{model}:predict"
    )


class VertexEmbeddingProvider:
    """Real Vertex AI client. Used in production; tests mock requests.post."""

    def __init__(
        self,
        auth: VertexAuth | None = None,
        *,
        text_model: str | None = None,
        image_model: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int | None = None,
    ):
        self.auth = auth or default_vertex_auth()
        self.text_model = text_model or config.get("EL_EMBEDDINGS_TEXT_MODEL", DEFAULT_TEXT_MODEL)
        self.image_model = image_model or config.get("EL_EMBEDDINGS_IMAGE_MODEL", DEFAULT_IMAGE_MODEL)
        self.timeout = timeout
        if max_retries is None:
            raw = config.get("EL_EMBEDDINGS_MAX_RETRIES", str(DEFAULT_MAX_RETRIES))
            try:
                max_retries = int(raw)
            except (TypeError, ValueError):
                max_retries = DEFAULT_MAX_RETRIES
        self.max_retries = max(1, max_retries)

    # -- public -------------------------------------------------------------

    def embed_text(self, text: str) -> list[float]:
        body = {"instances": [{"content": text}]}
        payload = self._post_with_retry(self.text_model, body)
        try:
            values = payload["predictions"][0]["embeddings"]["values"]
        except (KeyError, IndexError, TypeError) as exc:
            raise EmbeddingError(f"unexpected text embedding shape: {exc}") from exc
        return list(values)

    def embed_image(self, image_url: str) -> list[float]:
        # multimodalembedding@001 accepts image bytes (base64) or a gcs:// URI.
        # HTTP URLs are not accepted directly — download and pass as bytes.
        img_bytes = self._download_image(image_url)
        b64 = base64.b64encode(img_bytes).decode("ascii")
        body = {"instances": [{"image": {"bytesBase64Encoded": b64}}]}
        payload = self._post_with_retry(self.image_model, body)
        try:
            values = payload["predictions"][0]["imageEmbedding"]
        except (KeyError, IndexError, TypeError) as exc:
            raise EmbeddingError(f"unexpected image embedding shape: {exc}") from exc
        return list(values)

    # -- internals ----------------------------------------------------------

    def _download_image(self, image_url: str) -> bytes:
        try:
            resp = requests.get(image_url, timeout=self.timeout)
            resp.raise_for_status()
            return resp.content
        except Exception as exc:
            raise EmbeddingError(f"image download failed: {image_url}: {exc}") from exc

    def _post_with_retry(self, model: str, body: dict) -> dict:
        url = _vertex_predict_url(self.auth, model)
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                headers = {
                    "Authorization": f"Bearer {self.auth.get_token()}",
                    "Content-Type": "application/json",
                }
                resp = requests.post(url, json=body, headers=headers, timeout=self.timeout)
                if resp.status_code in RETRY_STATUS:
                    last_exc = EmbeddingError(f"HTTP {resp.status_code} (retryable)")
                    self._sleep_backoff(attempt)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                break
        raise EmbeddingError(f"vertex {model} failed after {self.max_retries} attempts: {last_exc}")

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        # 1s, 2s, 4s …
        time.sleep(2 ** (attempt - 1))


class FakeEmbeddingProvider:
    """Deterministic in-process embedding provider for tests.

    Hashes the input to seed a pseudo-vector. Same input → same vector;
    different inputs → different vectors. Vector entries are in [-1, 1].
    """

    def embed_text(self, text: str) -> list[float]:
        return self._vec(text.encode("utf-8"), TEXT_DIM)

    def embed_image(self, image_url: str) -> list[float]:
        return self._vec(image_url.encode("utf-8"), IMAGE_DIM)

    @staticmethod
    def _vec(seed_bytes: bytes, dim: int) -> list[float]:
        # Expand by repeated sha256 → enough bytes for any dim.
        out: list[float] = []
        digest = hashlib.sha256(seed_bytes).digest()
        i = 0
        while len(out) < dim:
            if i >= len(digest):
                digest = hashlib.sha256(digest).digest()
                i = 0
            byte = digest[i]
            i += 1
            out.append((byte / 127.5) - 1.0)
        return out
