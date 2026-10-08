"""Storefront FAQ snapshot ↔ Weaviate `NgocNganKnowledge` indexing and search."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.ai import chat_tools
from app.features.knowledge import faq_indexer, retriever
from app.features.knowledge.faq_indexer import (
    FAQ_SNAPSHOT_PATH,
    load_faq_snapshot,
    reindex_all_faqs,
)
from app.features.knowledge.weaviate import (
    COLLECTION_NAME,
    KnowledgeSourceType,
    knowledge_object_uuid,
)

_TEXT_FIELDS = ("question", "answer", "question_vi", "answer_vi")


def _settings(**overrides: Any) -> Any:
    values = {"weaviate_enabled": True, "rag_top_k": 3, "openai_api_key": None}
    values.update(overrides)
    return SimpleNamespace(**values)


def _faq(faq_id: str, **overrides: Any) -> SimpleNamespace:
    values = {
        "id": faq_id,
        "slug": faq_id,
        "category": "delivery",
        "category_label": "Delivery",
        "category_label_vi": "Giao hàng",
        "question": f"Question {faq_id}?",
        "answer": f"Answer {faq_id}.",
        "question_vi": f"Câu hỏi {faq_id}?",
        "answer_vi": f"Trả lời {faq_id}.",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _InMemoryFaqKnowledge:
    """Captures FAQ wipe/upsert calls made against `NgocNganKnowledge`."""

    def __init__(self) -> None:
        self.objects: list[dict[str, Any]] = [{"source_id": "removedFaq"}]
        self.calls: list[str] = []

    def delete_by_type(self, *, source_type: Any, **_: Any) -> None:
        assert str(source_type) == KnowledgeSourceType.FAQ.value
        self.calls.append("delete")
        self.objects = []

    def upsert(self, objects: list[dict[str, Any]], **_: Any) -> int:
        self.calls.append("upsert")
        self.objects.extend(objects)
        return len(objects)


@pytest.fixture
def faq_store(monkeypatch: pytest.MonkeyPatch) -> _InMemoryFaqKnowledge:
    store = _InMemoryFaqKnowledge()
    monkeypatch.setattr(faq_indexer, "get_weaviate_client", lambda *_a, **_k: object())
    monkeypatch.setattr(
        faq_indexer, "ensure_knowledge_collection", lambda *_a, **_k: object()
    )
    monkeypatch.setattr(
        faq_indexer, "delete_knowledge_by_source_type", store.delete_by_type
    )
    monkeypatch.setattr(faq_indexer, "upsert_knowledge_objects", store.upsert)
    return store


def test_committed_snapshot_has_complete_bilingual_items() -> None:
    faqs = load_faq_snapshot()

    assert faqs, f"Expected exported FAQs at {FAQ_SNAPSHOT_PATH}"
    ids = [faq.id for faq in faqs]
    assert len(ids) == len(set(ids))
    for faq in faqs:
        assert faq.slug == faq.id
        for field in _TEXT_FIELDS:
            assert str(getattr(faq, field, "")).strip(), f"{faq.id}.{field} is empty"


def test_load_faq_snapshot_missing_file_returns_none(tmp_path: Path) -> None:
    assert load_faq_snapshot(tmp_path / "missing.json") is None


def test_load_faq_snapshot_skips_items_without_id(tmp_path: Path) -> None:
    snapshot = tmp_path / "faqs.json"
    snapshot.write_text(
        json.dumps({"items": [{"id": "shippingCost", "question": "Q"}, {"id": ""}]}),
        encoding="utf-8",
    )

    faqs = load_faq_snapshot(snapshot)

    assert [faq.id for faq in faqs or []] == ["shippingCost"]


@pytest.mark.asyncio
async def test_reindex_wipes_old_faqs_then_inserts_bilingual_chunks(
    faq_store: _InMemoryFaqKnowledge,
) -> None:
    faqs = [_faq("nationwide"), _faq("shippingCost")]

    total = await reindex_all_faqs(settings=_settings(), faqs=faqs)

    assert total == 4
    assert faq_store.calls == ["delete", "upsert"]
    assert {obj["source_id"] for obj in faq_store.objects} == {
        "nationwide",
        "shippingCost",
    }
    for obj in faq_store.objects:
        assert obj["source_type"] == KnowledgeSourceType.FAQ.value
        assert obj["uuid"] == knowledge_object_uuid(
            source_type=KnowledgeSourceType.FAQ,
            source_id=obj["source_id"],
            chunk_id=obj["chunk_id"],
            locale=obj["locale"],
        )

    by_locale = {
        (obj["source_id"], obj["locale"]): obj for obj in faq_store.objects
    }
    vi = by_locale[("nationwide", "vi")]
    assert vi["title"] == "Câu hỏi nationwide?"
    assert "Chủ đề: Giao hàng" in vi["content"]
    assert "Trả lời: Trả lời nationwide." in vi["content"]
    en = by_locale[("nationwide", "en")]
    assert en["title"] == "Question nationwide?"
    assert "Topic: Delivery" in en["content"]


@pytest.mark.asyncio
async def test_reindex_skips_inactive_faqs(faq_store: _InMemoryFaqKnowledge) -> None:
    faqs = [_faq("nationwide"), _faq("oldFaq", is_active=False)]

    total = await reindex_all_faqs(settings=_settings(), faqs=faqs)

    assert total == 2
    assert {obj["source_id"] for obj in faq_store.objects} == {"nationwide"}


@pytest.mark.asyncio
async def test_reindex_without_snapshot_leaves_index_untouched(
    faq_store: _InMemoryFaqKnowledge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(faq_indexer, "load_faq_snapshot", lambda *_a, **_k: None)

    total = await reindex_all_faqs(settings=_settings())

    assert total == 0
    assert faq_store.calls == []
    assert faq_store.objects == [{"source_id": "removedFaq"}]


@pytest.mark.asyncio
async def test_reindex_disabled_weaviate_is_noop(
    faq_store: _InMemoryFaqKnowledge,
) -> None:
    total = await reindex_all_faqs(
        settings=_settings(weaviate_enabled=False), faqs=[_faq("nationwide")]
    )

    assert total == 0
    assert faq_store.calls == []


class _FakeCollection:
    def __init__(self) -> None:
        self.bm25_kwargs: dict[str, Any] = {}
        self.query = SimpleNamespace(bm25=self._bm25)

    def _bm25(self, **kwargs: Any) -> Any:
        self.bm25_kwargs = kwargs
        return SimpleNamespace(
            objects=[
                SimpleNamespace(
                    properties={
                        "title": "Phí ship cây giống bao nhiêu?",
                        "slug": "shippingCost",
                        "locale": "vi",
                        "content": "Trả lời: Đơn trên 500.000₫ được miễn phí.",
                    }
                )
            ]
        )


def test_search_faq_knowledge_queries_faq_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _FakeCollection()
    requested: list[str] = []

    def get_collection(name: str) -> _FakeCollection:
        requested.append(name)
        return collection

    fake_client = SimpleNamespace(
        collections=SimpleNamespace(exists=lambda _name: True, get=get_collection)
    )
    monkeypatch.setattr(retriever, "get_weaviate_client", lambda *_a, **_k: fake_client)

    result = retriever.search_faq_knowledge(
        "phí ship", locale="vi", settings=_settings()
    )

    assert requested == [COLLECTION_NAME]
    assert result["found"] is True
    assert result["chunks"][0]["slug"] == "shippingCost"
    assert collection.bm25_kwargs["query"] == "phí ship"
    assert collection.bm25_kwargs["limit"] == retriever.FAQ_TOP_K * 2
    conditions = {
        (condition.target, condition.value)
        for condition in collection.bm25_kwargs["filters"].filters
    }
    assert conditions == {("source_type", "faq"), ("locale", "vi")}


def test_search_faq_knowledge_keeps_one_locale_per_faq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def chunk(slug: str, locale: str) -> dict[str, Any]:
        return {
            "title": slug,
            "slug": slug,
            "locale": locale,
            "section": "",
            "content": slug,
        }

    monkeypatch.setattr(
        retriever,
        "_search_collection",
        lambda *_a, **_k: {
            "found": True,
            "query": "ship",
            "chunks": [
                chunk("shippingCost", "vi"),
                chunk("shippingCost", "en"),
                chunk("nationwide", "vi"),
                chunk("nationwide", "en"),
                chunk("trackOrder", "vi"),
            ],
        },
    )

    result = retriever.search_faq_knowledge("ship", limit=2, settings=_settings())

    assert [(c["slug"], c["locale"]) for c in result["chunks"]] == [
        ("shippingCost", "vi"),
        ("nationwide", "vi"),
    ]


def test_search_faq_knowledge_rejects_empty_query() -> None:
    result = retriever.search_faq_knowledge("   ", settings=_settings())

    assert result == {"found": False, "chunks": [], "error": "Empty search query"}


@pytest.mark.asyncio
async def test_execute_chat_tool_dispatches_search_shop_faq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_search(query: str, *, locale: str | None = None) -> dict[str, Any]:
        calls.append({"query": query, "locale": locale})
        return {"found": True, "chunks": [], "query": query}

    monkeypatch.setattr(chat_tools, "search_faq_knowledge", fake_search)

    result = await chat_tools.execute_chat_tool(
        "search_shop_faq",
        json.dumps({"query": "có giao đi tỉnh không", "locale": "vi"}),
        session=None,  # type: ignore[arg-type]
    )

    assert result["found"] is True
    assert calls == [{"query": "có giao đi tỉnh không", "locale": "vi"}]


def test_search_shop_faq_tool_is_registered() -> None:
    names = [tool["function"]["name"] for tool in chat_tools.CHAT_TOOLS]

    assert "search_shop_faq" in names
