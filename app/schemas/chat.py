"""Chat request schemas (streaming storefront assistant)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ChatRole = Literal["user", "assistant"]


class ChatMessage(BaseModel):
    """One turn of client-held conversation history."""

    role: ChatRole
    content: str = Field(min_length=1, max_length=8000)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Message content is required")
        return stripped


class ChatStreamRequest(BaseModel):
    """Body for ``POST /api/v1/chat/stream``."""

    message: str = Field(min_length=1, max_length=8000)
    conversation: list[ChatMessage] = Field(default_factory=list, max_length=40)

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Message is required")
        return stripped
