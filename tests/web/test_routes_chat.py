"""SP4 — /api/chat SSE route."""
from __future__ import annotations

import json


def _parse_sse(body: bytes) -> list[dict]:
    """Extract JSON payloads from each SSE `data:` line."""
    events = []
    for line in body.decode("utf-8").splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


def test_chat_requires_auth(client):
    r = client.post("/api/chat", json={"question": "x"})
    assert r.status_code == 401


def test_chat_validation_empty_question(client, auth_headers):
    r = client.post("/api/chat", headers=auth_headers, json={"question": ""})
    assert r.status_code == 422


def test_chat_streams_context_chunks_done(client, auth_headers):
    r = client.post("/api/chat", headers=auth_headers, json={"question": "best earbuds?"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(r.content)
    kinds = [e["event"] for e in events]
    assert kinds[0] == "context"
    assert "chunk" in kinds
    assert kinds[-1] == "done"


def test_chat_top_k_override(client, auth_headers, monkeypatch):
    """Body's top_k overrides Settings default; passed through to chat_rag."""
    captured: dict = {}
    from el.web import chat_rag as chat_rag_mod
    original = chat_rag_mod.stream_answer

    def spy(**kwargs):
        captured.update(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(chat_rag_mod, "stream_answer", spy)
    client.post("/api/chat", headers=auth_headers, json={"question": "x", "top_k": 12})
    assert captured["top_k"] == 12
