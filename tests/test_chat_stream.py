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
from app.features.admins.models import Admin
from app.features.categories.models import Category
from app.features.chat import tools as chat_tools
from app.features.chat.deepseek import (
    FALLBACK_REPLY,
    MAX_STREAM_TOOL_ROUNDS,
    DeepSeekService,
)
from app.features.chat.tools import check_stock, get_plant_price
from app.features.plants.models import Plant

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
    monkeypatch.setattr("app.features.chat.router.get_settings", lambda: settings)

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
    monkeypatch.setattr("app.features.chat.router.get_settings", lambda: settings)

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
    monkeypatch.setattr("app.features.chat.router.get_settings", lambda: settings)

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
    monkeypatch.setattr("app.features.chat.router.get_settings", lambda: settings)

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
    monkeypatch.setattr("app.features.chat.router.get_settings", lambda: settings)

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
    monkeypatch.setattr("app.features.chat.router.get_settings", lambda: settings)

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
    monkeypatch.setattr("app.features.chat.router.get_settings", lambda: settings)

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
    monkeypatch.setattr("app.features.chat.router.get_settings", lambda: settings)

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


# --- DSML tool-call markup leak regressions ---------------------------------

LEAKED_DSML = (
    "<｜｜DSML｜｜ calls> <｜｜DSML｜｜ invoke name=\"search_shop_faq\"> "
    "<｜｜DSML｜｜ parameter name=\"locale\" string=\"true\">vi</｜｜DSML｜｜ parameter> "
    "<｜｜DSML｜｜ parameter name=\"query\" string=\"true\">thanh toán COD trả tiền mặt "
    "khi nhận hàng chuyển khoản</｜｜DSML｜｜ parameter> </｜｜DSML｜｜ invoke> "
    "</｜｜DSML｜｜ calls>"
)


def _configure_deepseek(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key-not-real")
    monkeypatch.setattr("app.features.chat.router.get_settings", lambda: settings)


def _use_test_db_for_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Router imports AsyncSessionLocal by name; point it at the test database."""
    from app.core import database as database_module

    monkeypatch.setattr(
        "app.features.chat.router.AsyncSessionLocal", database_module.AsyncSessionLocal
    )


def _install_fake_client(monkeypatch: pytest.MonkeyPatch, create: Any) -> AsyncMock:
    create_mock = AsyncMock(side_effect=create)
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock))
    )
    monkeypatch.setattr(DeepSeekService, "_get_client", lambda self: fake_client)
    return create_mock


def _delta_chunk(content: str | None = None, tool_calls: list[Any] | None = None) -> Any:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=tool_calls))
        ]
    )


def _stream_of(*chunks: Any) -> AsyncIterator[Any]:
    async def gen() -> AsyncIterator[Any]:
        for chunk in chunks:
            yield chunk

    return gen()


def _stream_text(*parts: str) -> AsyncIterator[Any]:
    return _stream_of(*(_delta_chunk(content=p) for p in parts))


def _chunk_text(events: list[dict]) -> str:
    return "".join(e.get("content", "") for e in events if e.get("type") == "chunk")


def _assert_no_markup(events: list[dict]) -> None:
    for event in events:
        content = event.get("content", "") or ""
        assert "DSML" not in content
        assert "｜" not in content
        assert "invoke" not in content


def _install_faq_spy(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_faq(*, query: str, locale: str | None = None) -> dict[str, Any]:
        calls.append({"query": query, "locale": locale})
        return {
            "found": True,
            "chunks": [{"content": "Shop hỗ trợ COD toàn quốc.", "locale": "vi"}],
        }

    monkeypatch.setattr(chat_tools, "search_shop_faq_tool", fake_faq)
    return calls


@pytest.mark.asyncio
async def test_routing_reply_with_dsml_content_executes_tool(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DeepSeek put DSML in ``content`` with no ``tool_calls`` during routing."""
    _configure_deepseek(monkeypatch)
    faq_calls = _install_faq_spy(monkeypatch)
    routing_rounds = {"n": 0}
    stream_requests: list[list[dict[str, Any]]] = []

    async def create(**kwargs: Any) -> Any:
        if kwargs.get("stream"):
            stream_requests.append(list(kwargs["messages"]))
            return _stream_text("Dạ, shop ", "có hỗ trợ COD.")
        routing_rounds["n"] += 1
        if routing_rounds["n"] == 1:
            return _completion(content=LEAKED_DSML, tool_calls=[])
        return _completion(content=None, tool_calls=[])

    _install_fake_client(monkeypatch, create)

    response = await client.post(
        CHAT_STREAM,
        json={"message": "Shop có nhận COD không?", "conversation": []},
    )
    assert response.status_code == 200
    events = _parse_sse_frames(response.text)
    _assert_no_markup(events)
    assert events[-1] == {"type": "done"}
    assert _chunk_text(events) == "Dạ, shop có hỗ trợ COD."
    assert faq_calls == [
        {"query": "thanh toán COD trả tiền mặt khi nhận hàng chuyển khoản", "locale": "vi"}
    ]

    sent = stream_requests[0]
    assistant = next(m for m in sent if m.get("tool_calls"))
    assert assistant["content"] is None
    tool_msg = next(m for m in sent if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == assistant["tool_calls"][0]["id"]
    assert "COD" in tool_msg["content"]


@pytest.mark.asyncio
async def test_stream_dsml_split_across_deltas_is_executed_not_leaked(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Final stream starts writing DSML mid-answer, split across chunks."""
    _configure_deepseek(monkeypatch)
    faq_calls = _install_faq_spy(monkeypatch)
    stream_requests: list[dict[str, Any]] = []

    async def create(**kwargs: Any) -> Any:
        if not kwargs.get("stream"):
            return _completion(content=None, tool_calls=[])
        stream_requests.append({**kwargs, "messages": list(kwargs["messages"])})
        if len(stream_requests) == 1:
            return _stream_text("Dạ ", "<｜", LEAKED_DSML[2:40], LEAKED_DSML[40:])
        return _stream_text("shop ", "nhận COD ", "toàn quốc.")

    _install_fake_client(monkeypatch, create)

    response = await client.post(
        CHAT_STREAM,
        json={"message": "Thanh toán COD được không?", "conversation": []},
    )
    assert response.status_code == 200
    events = _parse_sse_frames(response.text)
    _assert_no_markup(events)
    assert events[-1] == {"type": "done"}
    assert _chunk_text(events) == "Dạ shop nhận COD toàn quốc."
    assert len(faq_calls) == 1
    assert faq_calls[0]["locale"] == "vi"

    assert len(stream_requests) == 2
    # Tools must be declared on streaming requests, or DeepSeek writes DSML text.
    assert all(r.get("tools") for r in stream_requests)
    second = stream_requests[1]["messages"]
    assistant = next(m for m in second if m.get("tool_calls"))
    assert assistant["content"] == "Dạ"
    assert any(m["role"] == "tool" for m in second)


@pytest.mark.asyncio
async def test_stream_native_tool_call_deltas_are_executed(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_moringa(test_db_session, test_category)
    _configure_deepseek(monkeypatch)
    _use_test_db_for_chat(monkeypatch)
    stream_requests: list[list[dict[str, Any]]] = []

    def tc_delta(**fields: Any) -> Any:
        function = SimpleNamespace(
            name=fields.get("name"), arguments=fields.get("arguments")
        )
        return SimpleNamespace(index=0, id=fields.get("id"), function=function)

    async def create(**kwargs: Any) -> Any:
        if not kwargs.get("stream"):
            return _completion(content=None, tool_calls=[])
        stream_requests.append(list(kwargs["messages"]))
        if len(stream_requests) == 1:
            return _stream_of(
                _delta_chunk(tool_calls=[tc_delta(id="s1", name="check_stock", arguments="")]),
                _delta_chunk(tool_calls=[tc_delta(arguments='{"plant_query": ')]),
                _delta_chunk(tool_calls=[tc_delta(arguments='"Cây Chùm Ngây"}')]),
            )
        return _stream_text("Còn ", "12 cây.")

    _install_fake_client(monkeypatch, create)

    response = await client.post(
        CHAT_STREAM,
        json={"message": "Cây Chùm Ngây còn hàng không?", "conversation": []},
    )
    assert response.status_code == 200
    events = _parse_sse_frames(response.text)
    assert _chunk_text(events) == "Còn 12 cây."
    assert events[-1] == {"type": "done"}

    second = stream_requests[1]
    assistant = next(m for m in second if m.get("tool_calls"))
    assert assistant["tool_calls"][0]["id"] == "s1"
    assert assistant["tool_calls"][0]["function"]["name"] == "check_stock"
    tool_msg = next(m for m in second if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "s1"
    assert json.loads(tool_msg["content"])["stock"] == 12


@pytest.mark.asyncio
async def test_multi_step_tool_rounds_execute_in_order(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_moringa(test_db_session, test_category)
    _configure_deepseek(monkeypatch)
    _use_test_db_for_chat(monkeypatch)
    order: list[str] = []

    async def tracked_price(session: Any, *, plant_query: str) -> dict[str, Any]:
        order.append("get_plant_price")
        return await get_plant_price(session, plant_query=plant_query)

    async def tracked_faq(*, query: str, locale: str | None = None) -> dict[str, Any]:
        order.append("search_shop_faq")
        return {"found": True, "chunks": [{"content": "Giao 2-3 ngày."}]}

    monkeypatch.setattr(chat_tools, "get_plant_price", tracked_price)
    monkeypatch.setattr(chat_tools, "search_shop_faq_tool", tracked_faq)

    routing_rounds = {"n": 0}
    stream_requests: list[list[dict[str, Any]]] = []

    async def create(**kwargs: Any) -> Any:
        if kwargs.get("stream"):
            stream_requests.append(list(kwargs["messages"]))
            return _stream_text("Giá 150.000đ, ", "giao 2-3 ngày.")
        routing_rounds["n"] += 1
        if routing_rounds["n"] == 1:
            return _completion(
                tool_calls=[_tool_call("get_plant_price", {"plant_query": "Chùm Ngây"}, "p1")]
            )
        if routing_rounds["n"] == 2:
            return _completion(
                tool_calls=[
                    _tool_call("search_shop_faq", {"query": "giao hàng", "locale": "vi"}, "f1")
                ]
            )
        return _completion(content=None, tool_calls=[])

    create_mock = _install_fake_client(monkeypatch, create)

    response = await client.post(
        CHAT_STREAM,
        json={"message": "Chùm Ngây giá bao nhiêu, giao mấy ngày?", "conversation": []},
    )
    assert response.status_code == 200
    events = _parse_sse_frames(response.text)
    assert _chunk_text(events) == "Giá 150.000đ, giao 2-3 ngày."
    assert order == ["get_plant_price", "search_shop_faq"]
    assert create_mock.await_count == 4  # 3 routing + 1 stream

    sent = stream_requests[0]
    roles = [m["role"] for m in sent]
    assert roles == ["system", "user", "assistant", "tool", "assistant", "tool"]
    assert sent[2]["tool_calls"][0]["id"] == sent[3]["tool_call_id"] == "p1"
    assert sent[4]["tool_calls"][0]["id"] == sent[5]["tool_call_id"] == "f1"
    assert json.loads(sent[3]["content"])["price"] == "150000.00"


@pytest.mark.asyncio
async def test_stream_tool_rounds_exhausted_emits_fallback_only(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_deepseek(monkeypatch)
    faq_calls = _install_faq_spy(monkeypatch)
    stream_count = {"n": 0}

    async def create(**kwargs: Any) -> Any:
        if not kwargs.get("stream"):
            return _completion(content=None, tool_calls=[])
        stream_count["n"] += 1
        return _stream_text(LEAKED_DSML[:15], LEAKED_DSML[15:])

    _install_fake_client(monkeypatch, create)

    response = await client.post(
        CHAT_STREAM,
        json={"message": "COD?", "conversation": []},
    )
    assert response.status_code == 200
    events = _parse_sse_frames(response.text)
    _assert_no_markup(events)
    assert [e for e in events if e.get("type") == "chunk"] == [
        {"type": "chunk", "content": FALLBACK_REPLY}
    ]
    assert events[-1] == {"type": "done"}
    assert stream_count["n"] == MAX_STREAM_TOOL_ROUNDS + 1
    assert len(faq_calls) == MAX_STREAM_TOOL_ROUNDS


@pytest.mark.asyncio
async def test_stream_error_after_partial_output_is_safe(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_deepseek(monkeypatch)

    async def create(**kwargs: Any) -> Any:
        if not kwargs.get("stream"):
            return _completion(content=None, tool_calls=[])

        async def gen() -> AsyncIterator[Any]:
            yield _delta_chunk(content="Dạ ")
            raise RuntimeError("upstream exploded <｜DSML｜invoke>")

        return gen()

    _install_fake_client(monkeypatch, create)

    response = await client.post(CHAT_STREAM, json={"message": "COD?", "conversation": []})
    assert response.status_code == 200
    events = _parse_sse_frames(response.text)
    _assert_no_markup(events)
    assert events[0] == {"type": "chunk", "content": "Dạ "}
    assert events[-1] == {"type": "error", "message": "Chat request failed"}


def test_build_messages_strips_markup_from_assistant_history() -> None:
    service = DeepSeekService(settings=get_settings())
    messages = service.build_messages(
        message="Còn gì nữa không?",
        conversation=[
            {"role": "user", "content": "Có COD không?"},
            {"role": "assistant", "content": LEAKED_DSML},
            {"role": "user", "content": "Ship mấy ngày?"},
            {"role": "assistant", "content": "Dạ 2-3 ngày. " + LEAKED_DSML},
        ],
    )
    assert [m["role"] for m in messages] == ["system", "user", "user", "assistant", "user"]
    assert messages[3]["content"] == "Dạ 2-3 ngày."
    assert not any("DSML" in m["content"] for m in messages)
