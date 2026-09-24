"""Public streaming chat endpoint (DeepSeek)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.core.sse import sse_chunk, sse_done, sse_error
from app.schemas.chat import ChatStreamRequest
from app.services.ai.deepseek import (
    DeepSeekNotConfiguredError,
    DeepSeekService,
    get_deepseek_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


async def _stream_chat_events(
    *,
    payload: ChatStreamRequest,
    service: DeepSeekService,
) -> AsyncIterator[str]:
    try:
        async for text in service.stream_chat(
            message=payload.message,
            conversation=[m.model_dump() for m in payload.conversation],
        ):
            yield sse_chunk(text)
        yield sse_done()
    except DeepSeekNotConfiguredError:
        logger.error("Chat stream requested but DeepSeek is not configured")
        yield sse_error("Chat service is not configured")
    except TimeoutError:
        yield sse_error("Chat request timed out")
    except Exception:  # noqa: BLE001 — surface a safe message over SSE
        logger.exception("Chat stream failed")
        yield sse_error("Chat request failed")


@router.post(
    "/stream",
    summary="Stream a chat reply (SSE)",
    response_class=StreamingResponse,
    responses={
        status.HTTP_200_OK: {
            "description": "SSE stream of chat chunks",
            "content": {"text/event-stream": {}},
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "DeepSeek is not configured",
        },
    },
)
async def stream_chat(payload: ChatStreamRequest) -> StreamingResponse:
    """Stream an assistant reply as Server-Sent Events.

    Conversation history is accepted from the client and forwarded to DeepSeek;
    the backend does not persist it.
    """
    settings = get_settings()
    service = get_deepseek_service(settings)
    if not service.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chat service is not configured",
        )

    return StreamingResponse(
        _stream_chat_events(payload=payload, service=service),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
