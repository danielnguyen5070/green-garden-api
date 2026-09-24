"""Streaming chat endpoint tests (DeepSeek mocked)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.services.ai.deepseek import DeepSeekService


CHAT_STREAM = "/api/v1/chat/stream"


def _parse_sse_frames(body: str) -> list[dict]:
    events: list[dict] = []
    for block in body.split("\n\n"):
        line = block.strip()
        if not line.startswith("data:"):
            continue
        raw = line[len("data:") :].strip()
        if not raw:
            continue
        events.append(json.loads(raw))
    return events


@pytest.mark.asyncio
async def test_chat_stream_requires_deepseek_config(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "deepseek_api_key", None)
    monkeypatch.setattr("app.api.v1.chat.get_settings", lambda: settings)

    response = await client.post(
        CHAT_STREAM,
        json={"message": "How do I water monstera?", "conversation": []},
    )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_chat_stream_sse_chunks(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key-not-real")
    monkeypatch.setattr("app.api.v1.chat.get_settings", lambda: settings)

    async def fake_stream(
        self: DeepSeekService,
        *,
        message: str,
        conversation=None,
    ) -> AsyncIterator[str]:
        assert "monstera" in message.lower()
        assert conversation == [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        for part in ("Water ", "when ", "the soil is dry."):
            yield part

    monkeypatch.setattr(DeepSeekService, "stream_chat", fake_stream)

    response = await client.post(
        CHAT_STREAM,
        json={
            "message": "How do I water monstera?",
            "conversation": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"},
            ],
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse_frames(response.text)
    assert events[-1] == {"type": "done"}
    chunks = [e["content"] for e in events if e.get("type") == "chunk"]
    assert chunks == ["Water ", "when ", "the soil is dry."]
    assert not any(e.get("type") == "error" for e in events)


@pytest.mark.asyncio
async def test_chat_stream_errors_over_sse(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key-not-real")
    monkeypatch.setattr("app.api.v1.chat.get_settings", lambda: settings)

    async def failing_stream(self: DeepSeekService, **_: object) -> AsyncIterator[str]:
        if False:  # pragma: no cover — make this an async generator
            yield ""
        raise TimeoutError("DeepSeek request timed out")

    monkeypatch.setattr(DeepSeekService, "stream_chat", failing_stream)

    response = await client.post(
        CHAT_STREAM,
        json={"message": "Hello", "conversation": []},
    )
    assert response.status_code == 200
    events = _parse_sse_frames(response.text)
    assert any(e.get("type") == "error" for e in events)
    assert events[0]["type"] == "error"
    assert "timed out" in events[0]["message"].lower()


@pytest.mark.asyncio
async def test_chat_stream_validates_body(client: AsyncClient) -> None:
    response = await client.post(CHAT_STREAM, json={"message": "", "conversation": []})
    assert response.status_code == 422
