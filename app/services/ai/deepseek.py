"""DeepSeek chat client (OpenAI-compatible SDK)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

from openai import APIError, APITimeoutError, AsyncOpenAI, RateLimitError

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Answer briefly and directly.
Prefer 1–3 short paragraphs or bullet points.
Do not repeat the user's question.
Do not mention sources, RAG, Weaviate, internal tools, or implementation details.\
"""

ALLOWED_ROLES = frozenset({"system", "user", "assistant"})


class DeepSeekNotConfiguredError(RuntimeError):
    """Raised when DEEPSEEK_API_KEY is missing."""


class DeepSeekService:
    """Reusable async client for DeepSeek chat completions."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: AsyncOpenAI | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self._settings.deepseek_api_key)

    def _get_client(self) -> AsyncOpenAI:
        if not self._settings.deepseek_api_key:
            raise DeepSeekNotConfiguredError(
                "DeepSeek is not configured (set DEEPSEEK_API_KEY)"
            )
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._settings.deepseek_api_key,
                base_url=self._settings.deepseek_base_url.rstrip("/"),
                timeout=self._settings.deepseek_timeout_seconds,
            )
        return self._client

    def build_messages(
        self,
        *,
        message: str,
        conversation: Sequence[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        """Build the OpenAI-style messages list (system + history + current user)."""
        messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]

        for item in conversation or ():
            role = str(item.get("role", "")).strip().lower()
            content = str(item.get("content", "")).strip()
            if role not in ALLOWED_ROLES or role == "system" or not content:
                continue
            messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": message.strip()})
        return messages

    async def stream_chat(
        self,
        *,
        message: str,
        conversation: Sequence[dict[str, Any]] | None = None,
    ) -> AsyncIterator[str]:
        """Yield assistant text deltas as they arrive (``stream=True``)."""
        client = self._get_client()
        messages = self.build_messages(message=message, conversation=conversation)

        try:
            stream = await client.chat.completions.create(
                model=self._settings.deepseek_model,
                messages=messages,  # type: ignore[arg-type]
                stream=True,
            )
            async for chunk in stream:
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                content = getattr(delta, "content", None) if delta is not None else None
                if content:
                    yield content
        except APITimeoutError as exc:
            logger.exception("DeepSeek request timed out")
            raise TimeoutError("DeepSeek request timed out") from exc
        except RateLimitError as exc:
            logger.exception("DeepSeek rate limit exceeded")
            raise RuntimeError("DeepSeek rate limit exceeded") from exc
        except APIError as exc:
            logger.exception("DeepSeek API error: %s", exc)
            raise RuntimeError("DeepSeek API request failed") from exc


def get_deepseek_service(settings: Settings | None = None) -> DeepSeekService:
    return DeepSeekService(settings=settings)
