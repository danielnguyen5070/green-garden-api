"""Streaming chat + DeepSeek Function Calling routing tests."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.admin import Admin
from app.models.category import Category
from app.models.plant import Plant
from app.services.ai import chat_tools
from app.services.ai.deepseek import DeepSeekService
from app.services.ai.chat_tools import check_stock, get_plant_price


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


def _tool_call(name: str, arguments: dict[str, Any], call_id: str = "call_1") -> Any:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def _completion(*, content: str | None = None, tool_calls: list[Any] | None = None) -> Any:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=tool_calls or []),
                finish_reason="tool_calls" if tool_calls else "stop",
            )
        ]
    )


async def _seed_moringa(session: AsyncSession, category: Category) -> Plant:
    unique = uuid4().hex[:8]
    plant = Plant(
        category_id=category.id,
        name="Moringa Tree",
        name_vi="Cây Chùm Ngây",
        slug=f"moringa-tree-{unique}",
        description="Nutritious tree",
        description_vi="Cây dinh dưỡng",
        price=Decimal("150000.00"),
        price_vi=Decimal("150000.00"),
        stock=12,
        sku=f"MOR-{unique}",
        is_active=True,
        is_featured=False,
    )
    session.add(plant)
    await session.commit()
    await session.refresh(plant)
    return plant


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
async def test_chat_stream_greeting_direct_no_tools(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key-not-real")
    monkeypatch.setattr("app.api.v1.chat.get_settings", lambda: settings)

    async def create(**kwargs: Any) -> Any:
        if kwargs.get("stream"):
            async def gen() -> AsyncIterator[Any]:
                for part in ("Xin ", "chào! ", "Mình có thể giúp gì?"):
                    yield SimpleNamespace(
                        choices=[
                            SimpleNamespace(delta=SimpleNamespace(content=part))
                        ]
                    )

            return gen()
        # Tool-routing round: no tools → final answer is streamed separately.
        return _completion(content=None, tool_calls=[])

    create_mock = AsyncMock(side_effect=create)
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock))
    )
    monkeypatch.setattr(DeepSeekService, "_get_client", lambda self: fake_client)

    knowledge_calls: list[Any] = []
    monkeypatch.setattr(
        chat_tools,
        "search_plant_knowledge_tool",
        AsyncMock(side_effect=lambda **k: knowledge_calls.append(k) or {"found": False}),
    )
    price_spy = AsyncMock(wraps=get_plant_price)
    monkeypatch.setattr(chat_tools, "get_plant_price", price_spy)

    response = await client.post(
        CHAT_STREAM,
        json={"message": "Xin chào", "conversation": []},
    )
    assert response.status_code == 200
    events = _parse_sse_frames(response.text)
    assert events[-1] == {"type": "done"}
    chunks = [e["content"] for e in events if e.get("type") == "chunk"]
    assert chunks == ["Xin ", "chào! ", "Mình có thể giúp gì?"]
    assert price_spy.await_count == 0
    assert knowledge_calls == []
    # 1 tool-routing call + 1 streaming call
    assert create_mock.await_count == 2


@pytest.mark.asyncio
async def test_chat_stream_emits_progressive_sse_chunks(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Final answer must arrive as many small SSE chunks, not one blob."""
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key-not-real")
    monkeypatch.setattr("app.api.v1.chat.get_settings", lambda: settings)

    deltas = ["Cây", " Chùm", " Ngây", " hiện", " có", " giá", " tốt."]

    async def create(**kwargs: Any) -> Any:
        if kwargs.get("stream"):
            async def gen() -> AsyncIterator[Any]:
                for part in deltas:
                    yield SimpleNamespace(
                        choices=[
                            SimpleNamespace(delta=SimpleNamespace(content=part))
                        ]
                    )

            return gen()
        return _completion(content=None, tool_calls=[])

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(side_effect=create))
        )
    )
    monkeypatch.setattr(DeepSeekService, "_get_client", lambda self: fake_client)

    response = await client.post(
        CHAT_STREAM,
        json={"message": "Giới thiệu ngắn về cây chùm ngây", "conversation": []},
    )
    assert response.status_code == 200
    events = _parse_sse_frames(response.text)
    chunk_events = [e for e in events if e.get("type") == "chunk"]
    assert len(chunk_events) == len(deltas)
    assert [e["content"] for e in chunk_events] == deltas
    assert events[-1] == {"type": "done"}
    # Must not collapse into a single full-answer chunk
    assert not any(
        e.get("content") == "".join(deltas) for e in chunk_events
    )

@pytest.mark.asyncio
async def test_price_question_uses_postgres_not_weaviate(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plant = await _seed_moringa(test_db_session, test_category)
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key-not-real")
    monkeypatch.setattr("app.api.v1.chat.get_settings", lambda: settings)

    knowledge_calls: list[Any] = []

    async def fake_knowledge(**kwargs: Any) -> dict[str, Any]:
        knowledge_calls.append(kwargs)
        return {"found": False, "chunks": []}

    monkeypatch.setattr(chat_tools, "search_plant_knowledge_tool", fake_knowledge)

    async def create(**kwargs: Any) -> Any:
        if kwargs.get("stream"):
            async def gen() -> AsyncIterator[Any]:
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content="Giá khoảng 150.000đ.")
                        )
                    ]
                )

            return gen()
        # After tools run, next routing round has no tools → then stream.
        if create.calls > 0:  # type: ignore[attr-defined]
            return _completion(content=None, tool_calls=[])
        create.calls += 1  # type: ignore[attr-defined]
        return _completion(
            tool_calls=[
                _tool_call(
                    "get_plant_price",
                    {"plant_query": "Cây Chùm Ngây"},
                    call_id="price1",
                )
            ]
        )

    create.calls = 0  # type: ignore[attr-defined]

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=create)))
    )
    monkeypatch.setattr(DeepSeekService, "_get_client", lambda self: fake_client)

    response = await client.post(
        CHAT_STREAM,
        json={"message": "Cây Chùm Ngây giá bao nhiêu?", "conversation": []},
    )
    assert response.status_code == 200
    events = _parse_sse_frames(response.text)
    assert events[-1]["type"] == "done"
    text = "".join(e.get("content", "") for e in events if e.get("type") == "chunk")
    assert "150" in text
    assert knowledge_calls == []
    assert plant.name_vi == "Cây Chùm Ngây"


@pytest.mark.asyncio
async def test_stock_question_uses_postgres_not_weaviate(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_moringa(test_db_session, test_category)
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key-not-real")
    monkeypatch.setattr("app.api.v1.chat.get_settings", lambda: settings)

    knowledge_calls: list[Any] = []
    monkeypatch.setattr(
        chat_tools,
        "search_plant_knowledge_tool",
        AsyncMock(side_effect=lambda **k: knowledge_calls.append(k) or {"found": False}),
    )

    async def create(**kwargs: Any) -> Any:
        if kwargs.get("stream"):
            async def gen() -> AsyncIterator[Any]:
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="Còn hàng."))]
                )

            return gen()
        if create.calls > 0:  # type: ignore[attr-defined]
            return _completion(content=None, tool_calls=[])
        create.calls += 1  # type: ignore[attr-defined]
        return _completion(
            tool_calls=[
                _tool_call("check_stock", {"plant_query": "Cây Chùm Ngây"}, call_id="stock1")
            ]
        )

    create.calls = 0  # type: ignore[attr-defined]

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=create)))
    )
    monkeypatch.setattr(DeepSeekService, "_get_client", lambda self: fake_client)

    response = await client.post(
        CHAT_STREAM,
        json={"message": "Cây Chùm Ngây còn hàng không?", "conversation": []},
    )
    assert response.status_code == 200
    assert knowledge_calls == []
    events = _parse_sse_frames(response.text)
    assert any(e.get("type") == "chunk" for e in events)


@pytest.mark.asyncio
async def test_knowledge_question_uses_weaviate_not_price_stock(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key-not-real")
    monkeypatch.setattr("app.api.v1.chat.get_settings", lambda: settings)

    price_calls: list[Any] = []
    stock_calls: list[Any] = []
    knowledge_calls: list[Any] = []

    async def fake_price(session: Any, *, plant_query: str) -> dict[str, Any]:
        price_calls.append(plant_query)
        return {"found": False}

    async def fake_stock(session: Any, *, plant_query: str) -> dict[str, Any]:
        stock_calls.append(plant_query)
        return {"found": False}

    async def fake_knowledge(*, query: str, locale: str | None = None) -> dict[str, Any]:
        knowledge_calls.append({"query": query, "locale": locale})
        return {
            "found": True,
            "chunks": [
                {
                    "title": "Cây Chùm Ngây",
                    "section": "Ánh sáng",
                    "content": "Chùm Ngây ưa sáng, thích nắng trực tiếp buổi sáng.",
                    "locale": "vi",
                    "slug": "moringa-tree",
                }
            ],
        }

    monkeypatch.setattr(chat_tools, "get_plant_price", fake_price)
    monkeypatch.setattr(chat_tools, "check_stock", fake_stock)
    monkeypatch.setattr(chat_tools, "search_plant_knowledge_tool", fake_knowledge)

    round_state = {"n": 0}

    async def create(**kwargs: Any) -> Any:
        if kwargs.get("stream"):
            async def gen() -> AsyncIterator[Any]:
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content="Có, cây này cần nhiều ánh sáng."
                            )
                        )
                    ]
                )

            return gen()
        round_state["n"] += 1
        if round_state["n"] == 1:
            return _completion(
                tool_calls=[
                    _tool_call(
                        "search_plant_knowledge",
                        {"query": "Cây Chùm Ngây ánh sáng", "locale": "vi"},
                        call_id="know1",
                    )
                ]
            )
        return _completion(content=None, tool_calls=[])

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=create)))
    )
    monkeypatch.setattr(DeepSeekService, "_get_client", lambda self: fake_client)

    response = await client.post(
        CHAT_STREAM,
        json={"message": "Cây Chùm Ngây cần nhiều ánh sáng không?", "conversation": []},
    )
    assert response.status_code == 200
    assert len(knowledge_calls) == 1
    assert price_calls == []
    assert stock_calls == []


@pytest.mark.asyncio
async def test_mixed_price_and_knowledge_calls_both(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_moringa(test_db_session, test_category)
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key-not-real")
    monkeypatch.setattr("app.api.v1.chat.get_settings", lambda: settings)

    knowledge_calls: list[Any] = []

    async def fake_knowledge(*, query: str, locale: str | None = None) -> dict[str, Any]:
        knowledge_calls.append(query)
        return {
            "found": True,
            "chunks": [
                {
                    "section": "Ánh sáng",
                    "content": "Ưa sáng.",
                    "locale": "vi",
                    "title": "Cây Chùm Ngây",
                    "slug": "moringa-tree",
                }
            ],
        }

    monkeypatch.setattr(chat_tools, "search_plant_knowledge_tool", fake_knowledge)

    async def create(**kwargs: Any) -> Any:
        if kwargs.get("stream"):
            async def gen() -> AsyncIterator[Any]:
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content="Giá 150.000đ và cây ưa sáng."
                            )
                        )
                    ]
                )

            return gen()
        if create.calls > 0:  # type: ignore[attr-defined]
            return _completion(content=None, tool_calls=[])
        create.calls += 1  # type: ignore[attr-defined]
        return _completion(
            tool_calls=[
                _tool_call(
                    "get_plant_price",
                    {"plant_query": "Cây Chùm Ngây"},
                    call_id="p1",
                ),
                _tool_call(
                    "search_plant_knowledge",
                    {"query": "Cây Chùm Ngây ánh sáng", "locale": "vi"},
                    call_id="k1",
                ),
            ]
        )

    create.calls = 0  # type: ignore[attr-defined]

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=create)))
    )
    monkeypatch.setattr(DeepSeekService, "_get_client", lambda self: fake_client)

    response = await client.post(
        CHAT_STREAM,
        json={
            "message": "Cây Chùm Ngây giá bao nhiêu và cần nhiều ánh sáng không?",
            "conversation": [],
        },
    )
    assert response.status_code == 200
    assert len(knowledge_calls) == 1
    events = _parse_sse_frames(response.text)
    text = "".join(e.get("content", "") for e in events if e.get("type") == "chunk")
    assert "150" in text or "sáng" in text


@pytest.mark.asyncio
async def test_get_plant_price_and_check_stock_helpers(
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_moringa(test_db_session, test_category)
    price = await get_plant_price(test_db_session, plant_query="Chùm Ngây")
    assert price["found"] is True
    assert price["price"] == "150000.00"
    assert "sku" not in price

    stock = await check_stock(test_db_session, plant_query=plant.slug)
    assert stock["found"] is True
    assert stock["in_stock"] is True
    assert stock["stock"] == 12


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
        if False:  # pragma: no cover
            yield ""
        raise TimeoutError("DeepSeek request timed out")

    monkeypatch.setattr(DeepSeekService, "stream_chat", failing_stream)

    response = await client.post(
        CHAT_STREAM,
        json={"message": "Hello", "conversation": []},
    )
    assert response.status_code == 200
    events = _parse_sse_frames(response.text)
    assert events[0]["type"] == "error"


@pytest.mark.asyncio
async def test_chat_stream_validates_body(client: AsyncClient) -> None:
    response = await client.post(CHAT_STREAM, json={"message": "", "conversation": []})
    assert response.status_code == 422
