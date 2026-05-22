"""Tests for el/embeddings.py — Vertex multimodal embedding provider + fake."""
from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from el import embeddings


class _FakeAuth:
    """Stand-in for VertexAuth — no real OAuth."""
    project_id = "test-project"
    location = "global"
    def get_token(self) -> str:
        return "fake-token"


def _response(payload: dict, status_code: int = 200):
    from unittest.mock import MagicMock
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = payload
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status_code}")
    return resp


# -- EmbeddingProvider protocol -----------------------------------------------

def test_vertex_provider_satisfies_protocol():
    p = embeddings.VertexEmbeddingProvider(auth=_FakeAuth())
    assert isinstance(p, embeddings.EmbeddingProvider)


def test_fake_provider_satisfies_protocol():
    assert isinstance(embeddings.FakeEmbeddingProvider(), embeddings.EmbeddingProvider)


# -- embed_text ---------------------------------------------------------------

def test_embed_text_calls_text_model_endpoint():
    provider = embeddings.VertexEmbeddingProvider(auth=_FakeAuth())
    fake_resp = _response({
        "predictions": [{"embeddings": {"values": [0.1] * 768}}]
    })
    with patch.object(embeddings.requests, "post", return_value=fake_resp) as mock_post:
        vec = provider.embed_text("hello world")
    assert vec == [0.1] * 768
    url = mock_post.call_args.args[0]
    assert "text-embedding-005" in url
    assert "predict" in url
    headers = mock_post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer fake-token"
    assert mock_post.call_args.kwargs["timeout"] == 30


def test_embed_text_request_body_shape():
    provider = embeddings.VertexEmbeddingProvider(auth=_FakeAuth())
    fake_resp = _response({"predictions": [{"embeddings": {"values": [0.0] * 768}}]})
    with patch.object(embeddings.requests, "post", return_value=fake_resp) as mock_post:
        provider.embed_text("hi")
    body = mock_post.call_args.kwargs["json"]
    assert body == {"instances": [{"content": "hi"}]}


# -- embed_image --------------------------------------------------------------

def test_embed_image_calls_multimodal_endpoint():
    provider = embeddings.VertexEmbeddingProvider(auth=_FakeAuth())
    fake_resp = _response({
        "predictions": [{"imageEmbedding": [0.2] * 1408}]
    })

    class _FakeImgResp:
        status_code = 200
        content = b"\x89PNGfakebytes"
        def raise_for_status(self): pass

    with patch.object(embeddings.requests, "post", return_value=fake_resp) as mock_post, \
         patch.object(embeddings.requests, "get", return_value=_FakeImgResp()):
        vec = provider.embed_image("https://example.com/img.jpg")
    assert vec == [0.2] * 1408
    url = mock_post.call_args.args[0]
    assert "multimodalembedding@001" in url


def test_embed_image_request_body_uses_image_url_via_bytesBase64Encoded(monkeypatch):
    """multimodalembedding@001 doesn't accept HTTP URLs directly — provider
    downloads the image and submits as bytesBase64Encoded."""
    provider = embeddings.VertexEmbeddingProvider(auth=_FakeAuth())

    class _FakeImgResp:
        status_code = 200
        content = b"\x89PNGfakebytes"
        def raise_for_status(self): pass

    def fake_get(url, timeout=None):
        return _FakeImgResp()

    embed_resp = _response({"predictions": [{"imageEmbedding": [0.0] * 1408}]})
    with patch.object(embeddings.requests, "post", return_value=embed_resp) as mock_post, \
         patch.object(embeddings.requests, "get", side_effect=fake_get):
        provider.embed_image("https://example.com/img.jpg")
    body = mock_post.call_args.kwargs["json"]
    instance = body["instances"][0]
    assert "image" in instance
    assert "bytesBase64Encoded" in instance["image"]


# -- retry --------------------------------------------------------------------

def test_embed_text_retries_on_429(monkeypatch):
    provider = embeddings.VertexEmbeddingProvider(auth=_FakeAuth(), max_retries=3)
    monkeypatch.setattr(embeddings.time, "sleep", lambda s: None)
    calls = [_response({}, status_code=429), _response({}, status_code=503),
             _response({"predictions": [{"embeddings": {"values": [1.0] * 768}}]})]
    call_iter = iter(calls)
    with patch.object(embeddings.requests, "post", side_effect=lambda *a, **kw: next(call_iter)):
        vec = provider.embed_text("retry me")
    assert vec == [1.0] * 768


def test_embed_text_raises_after_max_retries(monkeypatch):
    provider = embeddings.VertexEmbeddingProvider(auth=_FakeAuth(), max_retries=2)
    monkeypatch.setattr(embeddings.time, "sleep", lambda s: None)
    with patch.object(embeddings.requests, "post",
                      return_value=_response({}, status_code=429)):
        with pytest.raises(embeddings.EmbeddingError):
            provider.embed_text("never works")


# -- fake provider ------------------------------------------------------------

def test_fake_provider_returns_deterministic_vectors_keyed_by_input():
    fake = embeddings.FakeEmbeddingProvider()
    v1 = fake.embed_text("abc")
    v2 = fake.embed_text("abc")
    v3 = fake.embed_text("xyz")
    assert v1 == v2
    assert v1 != v3
    assert len(v1) == 768


def test_fake_provider_image_has_correct_dim():
    fake = embeddings.FakeEmbeddingProvider()
    vec = fake.embed_image("https://x/y.jpg")
    assert len(vec) == 1408
