"""Build bilingual knowledge text and chunk payloads from PostgreSQL entities.

Price, stock, SKU, and other business fields are intentionally omitted —
PostgreSQL remains authoritative for those.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal, NotRequired, Protocol, TypedDict

from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from app.services.ai.knowledge.weaviate import (
    KnowledgeSourceType,
    knowledge_object_uuid,
)

Locale = Literal["en", "vi"]

CHUNK_MAIN = "main"

# Deterministic defaults for LangChain splitters (reusable by the indexer).
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 150

_MARKDOWN_HEADERS = [
    ("#", "h1"),
    ("##", "h2"),
    ("###", "h3"),
]


class PlantChunkMetadata(TypedDict):
    plant_id: str
    slug: str
    locale: Locale
    section: NotRequired[str]


class PlantChunk(TypedDict):
    """Vector-document shape ready for embedding / Weaviate indexing."""

    plant_id: str
    slug: str
    locale: Locale
    title: str
    content: str
    section: NotRequired[str]
    metadata: PlantChunkMetadata

# Plant columns used for semantic knowledge (from `app.models.plant.Plant`).
# Excluded on purpose: price, price_vi, stock, sku, og_image_url, is_*, timestamps.
_PLANT_CARE_ENUM_FIELDS = (
    "plant_type",
    "difficulty",
    "growth_rate",
    "sunlight",
    "watering",
    "space_requirement",
)
_PLANT_CARE_BOOL_FIELDS = (
    "indoor_suitable",
    "outdoor_suitable",
    "pet_safe",
    "beginner_friendly",
)

_EN_LABELS = {
    "name": "Name",
    "name_vi": "Vietnamese name",
    "description": "Description",
    "description_vi": "Vietnamese description",
    "long_description": "Long description",
    "long_description_vi": "Vietnamese long description",
    "plant_type": "Plant type",
    "difficulty": "Difficulty",
    "growth_rate": "Growth rate",
    "sunlight": "Sunlight",
    "watering": "Watering",
    "space_requirement": "Space requirement",
    "indoor_suitable": "Indoor suitable",
    "outdoor_suitable": "Outdoor suitable",
    "pet_safe": "Pet safe",
    "beginner_friendly": "Beginner friendly",
}

_VI_LABELS = {
    "name": "Tên tiếng Anh",
    "name_vi": "Tên",
    "description": "Mô tả tiếng Anh",
    "description_vi": "Mô tả",
    "long_description": "Mô tả chi tiết tiếng Anh",
    "long_description_vi": "Mô tả chi tiết",
    "plant_type": "Loại cây",
    "difficulty": "Độ khó chăm sóc",
    "growth_rate": "Tốc độ tăng trưởng",
    "sunlight": "Ánh sáng",
    "watering": "Tưới nước",
    "space_requirement": "Không gian",
    "indoor_suitable": "Phù hợp trong nhà",
    "outdoor_suitable": "Phù hợp ngoài trời",
    "pet_safe": "An toàn với thú cưng",
    "beginner_friendly": "Phù hợp người mới",
}


class _HasIdSlug(Protocol):
    id: uuid.UUID
    slug: str


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return _clean_text(getattr(value, "value", str(value)))


def _bool_label(value: bool | None, *, locale: Locale) -> str | None:
    if value is None:
        return None
    if locale == "vi":
        return "có" if value else "không"
    return "yes" if value else "no"


def _join_sections(sections: list[tuple[str, str | None]]) -> str:
    """Join labeled fields as plain ``Label: value`` lines (FAQ/blog helpers)."""
    parts: list[str] = []
    for label, text in sections:
        cleaned = _clean_text(text)
        if cleaned is None:
            continue
        parts.append(f"{label}: {cleaned}")
    return "\n".join(parts)


def _join_markdown_sections(sections: list[tuple[str, str | None]]) -> str:
    """Join fields as Markdown ``##`` sections for header-aware splitting.

    If a field already starts with a Markdown heading, it is kept as-is so
    nested headings inside long-form SEO copy become real sections.
    """
    parts: list[str] = []
    for label, text in sections:
        cleaned = _clean_text(text)
        if cleaned is None:
            continue
        if cleaned.lstrip().startswith("#"):
            parts.append(cleaned)
        else:
            parts.append(f"## {label}\n\n{cleaned}")
    return "\n\n".join(parts)


def _plant_content_sections(
    plant: Any, *, locale: Locale | None = None
) -> list[tuple[str, str | None]]:
    """Build ordered (section_label, text) pairs from Plant knowledge fields."""
    if locale == "vi":
        labels = _VI_LABELS
        sections: list[tuple[str, str | None]] = [
            (labels["name_vi"], getattr(plant, "name_vi", None)),
            (labels["description_vi"], getattr(plant, "description_vi", None)),
            (
                labels["long_description_vi"],
                getattr(plant, "long_description_vi", None),
            ),
        ]
        bool_locale: Locale = "vi"
        care_section = "Thuộc tính chăm sóc"
    elif locale == "en":
        labels = _EN_LABELS
        sections = [
            (labels["name"], getattr(plant, "name", None)),
            (labels["description"], getattr(plant, "description", None)),
            (labels["long_description"], getattr(plant, "long_description", None)),
        ]
        bool_locale = "en"
        care_section = "Care attributes"
    else:
        # Bilingual document: include each language field only when present.
        labels = _EN_LABELS
        sections = [
            (labels["name"], getattr(plant, "name", None)),
            (labels["name_vi"], getattr(plant, "name_vi", None)),
            (labels["description"], getattr(plant, "description", None)),
            (labels["description_vi"], getattr(plant, "description_vi", None)),
            (labels["long_description"], getattr(plant, "long_description", None)),
            (
                labels["long_description_vi"],
                getattr(plant, "long_description_vi", None),
            ),
        ]
        bool_locale = "en"
        care_section = "Care attributes"

    # Group structured care fields under one heading so they never collide with
    # Markdown headings already present inside long-form SEO copy.
    care_lines: list[str] = []
    for field in _PLANT_CARE_ENUM_FIELDS:
        value = _enum_value(getattr(plant, field, None))
        if value is not None:
            care_lines.append(f"{labels[field]}: {value}")
    for field in _PLANT_CARE_BOOL_FIELDS:
        value = _bool_label(getattr(plant, field, None), locale=bool_locale)
        if value is not None:
            care_lines.append(f"{labels[field]}: {value}")
    if care_lines:
        sections.append((care_section, "\n".join(care_lines)))

    return sections


def build_plant_content(plant: Any, *, locale: Locale | None = None) -> str:
    """Combine existing Plant knowledge fields into embeddable Markdown text.

    Uses only descriptive / care columns from PostgreSQL (`name`, `name_vi`,
    `description`, `description_vi`, `long_description`, `long_description_vi`,
    and care attributes). Empty values are skipped. Business fields (price,
    stock, SKU, etc.) are never included.

    Args:
        plant: A `Plant` ORM instance (or any object with the same attributes).
        locale: ``"en"`` / ``"vi"`` for a single-locale document, or ``None``
            to include both English and Vietnamese copy when available.
    """
    return _join_markdown_sections(_plant_content_sections(plant, locale=locale))


# Back-compat alias used by locale-split indexing.
def build_plant_knowledge_text(plant: Any, *, locale: Locale) -> str:
    """Compose plant knowledge for one locale from PostgreSQL fields."""
    return build_plant_content(plant, locale=locale)


def plant_title(plant: Any, *, locale: Locale) -> str:
    if locale == "vi":
        return (
            _clean_text(getattr(plant, "name_vi", None))
            or _clean_text(getattr(plant, "name", None))
            or ""
        )
    return _clean_text(getattr(plant, "name", None)) or ""


def _section_from_header_metadata(metadata: dict[str, Any]) -> str | None:
    """Prefer the most specific Markdown heading present on a split document."""
    for key in ("h3", "h2", "h1"):
        value = _clean_text(metadata.get(key))
        if value is not None:
            return value
    return None


def _with_heading_context(
    content: str, section: str | None, *, is_continuation: bool
) -> str:
    """Keep continuation chunks self-contained without rewriting the source text."""
    cleaned = content.strip()
    if not cleaned or not section or not is_continuation:
        return cleaned
    if cleaned.startswith(section):
        return cleaned
    return f"{section}\n\n{cleaned}"


def _plant_vector_document(
    *,
    plant_id: str,
    slug: str,
    locale: Locale,
    title: str,
    content: str,
    section: str | None,
) -> PlantChunk | None:
    cleaned = _clean_text(content)
    if cleaned is None:
        return None

    metadata: PlantChunkMetadata = {
        "plant_id": plant_id,
        "slug": slug,
        "locale": locale,
    }
    if section:
        metadata["section"] = section

    doc: dict[str, Any] = {
        "plant_id": plant_id,
        "slug": slug,
        "locale": locale,
        "title": title,
    }
    if section:
        doc["section"] = section
    doc["content"] = cleaned
    doc["metadata"] = metadata
    return doc  # type: ignore[return-value]


def prepare_plant_chunks(
    plant: Any,
    *,
    locale: Locale | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[PlantChunk]:
    """Chunk a Plant into deterministic vector-documents for embedding/indexing.

    Builds locale-specific Markdown from knowledge fields (no price/stock/SKU),
    splits with LangChain ``MarkdownHeaderTextSplitter`` +
    ``RecursiveCharacterTextSplitter``, then maps each piece to a consistent
    structure with plant identity + language metadata.

    Args:
        plant: A ``Plant`` ORM instance (or duck-typed equivalent).
        locale: ``"en"`` / ``"vi"`` for one language, or ``None`` for both.
        chunk_size: Max characters per chunk (RecursiveCharacterTextSplitter).
        chunk_overlap: Overlap between adjacent size-based chunks.

    Returns:
        Ordered list of chunk dicts ready for the embedding/indexing layer.
        Does not generate embeddings or write to Weaviate.
    """
    plant_id = str(getattr(plant, "id", "") or "")
    slug = _clean_text(getattr(plant, "slug", None)) or ""
    locales: tuple[Locale, ...] = (locale,) if locale is not None else ("en", "vi")

    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=_MARKDOWN_HEADERS,
        strip_headers=True,
    )
    size_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    results: list[PlantChunk] = []
    for loc in locales:
        markdown = build_plant_content(plant, locale=loc)
        if not markdown:
            continue

        title = plant_title(plant, locale=loc)
        header_docs = header_splitter.split_text(markdown)
        # No headings (or empty splitter output): treat the whole body as one doc.
        if not header_docs:
            header_docs = [Document(page_content=markdown, metadata={})]

        for header_doc in header_docs:
            section = _section_from_header_metadata(dict(header_doc.metadata))
            body = (header_doc.page_content or "").strip()
            if not body:
                continue

            pieces = size_splitter.split_text(body)
            if not pieces:
                pieces = [body]

            for index, piece in enumerate(pieces):
                content = _with_heading_context(
                    piece, section, is_continuation=index > 0
                )
                doc = _plant_vector_document(
                    plant_id=plant_id,
                    slug=slug,
                    locale=loc,
                    title=title,
                    content=content,
                    section=section,
                )
                if doc is not None:
                    results.append(doc)

    return results


def build_faq_knowledge_text(faq: Any, *, locale: Locale) -> str:
    if locale == "vi":
        question = getattr(faq, "question_vi", None)
        answer = getattr(faq, "answer_vi", None)
        q_label, a_label = "Câu hỏi", "Trả lời"
    else:
        question = getattr(faq, "question", None)
        answer = getattr(faq, "answer", None)
        q_label, a_label = "Question", "Answer"
    return _join_sections([(q_label, question), (a_label, answer)])


def faq_title(faq: Any, *, locale: Locale) -> str:
    if locale == "vi":
        return (
            _clean_text(getattr(faq, "question_vi", None))
            or _clean_text(getattr(faq, "title_vi", None))
            or ""
        )
    return (
        _clean_text(getattr(faq, "question", None))
        or _clean_text(getattr(faq, "title", None))
        or ""
    )


def build_blog_knowledge_text(blog: Any, *, locale: Locale) -> str:
    if locale == "vi":
        title = getattr(blog, "title_vi", None)
        summary = getattr(blog, "summary_vi", None)
        body = getattr(blog, "content_vi", None) or getattr(blog, "body_vi", None)
        labels = {"title": "Tiêu đề", "summary": "Tóm tắt", "content": "Nội dung"}
    else:
        title = getattr(blog, "title", None)
        summary = getattr(blog, "summary", None)
        body = getattr(blog, "content", None) or getattr(blog, "body", None)
        labels = {"title": "Title", "summary": "Summary", "content": "Content"}
    return _join_sections(
        [
            (labels["title"], title),
            (labels["summary"], summary),
            (labels["content"], body),
        ]
    )


def blog_title(blog: Any, *, locale: Locale) -> str:
    if locale == "vi":
        return _clean_text(getattr(blog, "title_vi", None)) or ""
    return _clean_text(getattr(blog, "title", None)) or ""


def knowledge_chunk(
    *,
    source_type: KnowledgeSourceType,
    source: _HasIdSlug,
    locale: Locale,
    title: str,
    content: str,
    chunk_id: str = CHUNK_MAIN,
    name: str | None = None,
    name_vi: str | None = None,
) -> dict[str, Any] | None:
    """Build one Weaviate-ready knowledge object, or None if content is empty."""
    cleaned = _clean_text(content)
    if cleaned is None:
        return None

    payload: dict[str, Any] = {
        "uuid": knowledge_object_uuid(
            source_type=source_type,
            source_id=source.id,
            chunk_id=chunk_id,
            locale=locale,
        ),
        "source_id": source.id,
        "source_type": source_type.value,
        "chunk_id": chunk_id,
        "locale": locale,
        "title": title,
        "slug": getattr(source, "slug", "") or "",
        "content": cleaned,
        "name": _clean_text(name) or "",
        "name_vi": _clean_text(name_vi) or "",
    }
    if source_type == KnowledgeSourceType.PLANT:
        payload["plant_id"] = str(source.id)
    else:
        payload["plant_id"] = ""
    return payload


def bilingual_chunks(
    *,
    source_type: KnowledgeSourceType,
    source: _HasIdSlug,
    build_text,
    build_title,
    chunk_id: str = CHUNK_MAIN,
    name: str | None = None,
    name_vi: str | None = None,
) -> list[dict[str, Any]]:
    """Create separate en/vi knowledge objects for a source record."""
    chunks: list[dict[str, Any]] = []
    for locale in ("en", "vi"):
        obj = knowledge_chunk(
            source_type=source_type,
            source=source,
            locale=locale,  # type: ignore[arg-type]
            title=build_title(source, locale=locale),  # type: ignore[arg-type]
            content=build_text(source, locale=locale),  # type: ignore[arg-type]
            chunk_id=chunk_id,
            name=name,
            name_vi=name_vi,
        )
        if obj is not None:
            chunks.append(obj)
    return chunks
