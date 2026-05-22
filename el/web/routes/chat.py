"""SP4 — /api/chat: SSE-streamed RAG answer."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from el.web import chat_rag
from el.web.deps import get_principal, get_settings

router = APIRouter(prefix="/api", tags=["chat"])


class ChatBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)


def _sse_format(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/chat")
def chat(
    body: ChatBody,
    _principal: str = Depends(get_principal),
    settings=Depends(get_settings),
):
    top_k = body.top_k or settings.chat_top_k

    def _generate():
        try:
            for event in chat_rag.stream_answer(
                question=body.question,
                top_k=top_k,
                embedding_provider=settings.embedding_provider,
                db_provider=settings.db_provider,
                llm_stream=settings.llm_stream,
            ):
                yield _sse_format(event)
        except Exception as exc:  # pragma: no cover - belt and braces
            yield _sse_format({"event": "error", "message": str(exc)})

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )
