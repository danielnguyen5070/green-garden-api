"""DeepSeek chat client with Function Calling routing (OpenAI-compatible SDK)."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

from openai import APIError, APITimeoutError, AsyncOpenAI, RateLimitError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.services.ai.chat_tools import CHAT_TOOLS, execute_chat_tool

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a helpful garden shop assistant.

Answer briefly and directly.
Prefer 1–3 short paragraphs or bullet points.
Do not repeat the user's question.

Routing rules (use tools when needed — do not invent live business data):
- Current price / cost / "giá" → always call get_plant_price.
- Stock / availability / "còn hàng" → always call check_stock.
- Plant care or descriptive knowledge (light, watering, soil, characteristics, \
growing tips) → call search_plant_knowledge.
- Greetings and general chat with no catalogue need → answer directly (no tools).
- If a question needs both business data and knowledge, call multiple tools.

Never mention tools, function calls, databases, Weaviate, RAG, or implementation details.\
"""

ALLOWED_ROLES = frozenset({"system", "user", "assistant"})
MAX_TOOL_ROUNDS = 3


class DeepSeekNotConfiguredError(RuntimeError):
    """Raised when DEEPSEEK_API_KEY is missing."""


class DeepSeekService:
    """Reusable async client for DeepSeek chat completions + tool routing."""

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
    ) -> list[dict[str, Any]]:
        """Build the OpenAI-style messages list (system + history + current user)."""
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

        for item in conversation or ():
            role = str(item.get("role", "")).strip().lower()
            content = str(item.get("content", "")).strip()
            if role not in ALLOWED_ROLES or role == "system" or not content:
                continue
            messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": message.strip()})
        return messages

    @staticmethod
    def _assistant_tool_message(message: Any) -> dict[str, Any]:
        tool_calls = []
        for tc in message.tool_calls or []:
            tool_calls.append(
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments or "{}",
                    },
                }
            )
        payload: dict[str, Any] = {
            "role": "assistant",
            "content": message.content,
            "tool_calls": tool_calls,
        }
        return payload

    async def _run_tool_rounds(
        self,
        *,
        client: AsyncOpenAI,
        messages: list[dict[str, Any]],
        session: AsyncSession,
    ) -> list[dict[str, Any]]:
        """Let DeepSeek request tools; execute them; append results. No SSE yet."""
        for _ in range(MAX_TOOL_ROUNDS):
            try:
                completion = await client.chat.completions.create(
                    model=self._settings.deepseek_model,
                    messages=messages,  # type: ignore[arg-type]
                    tools=CHAT_TOOLS,  # type: ignore[arg-type]
                    tool_choice="auto",
                )
            except APITimeoutError as exc:
                logger.exception("DeepSeek tool-routing request timed out")
                raise TimeoutError("DeepSeek request timed out") from exc
            except RateLimitError as exc:
                logger.exception("DeepSeek rate limit exceeded")
                raise RuntimeError("DeepSeek rate limit exceeded") from exc
            except APIError as exc:
                logger.exception("DeepSeek API error: %s", exc)
                raise RuntimeError("DeepSeek API request failed") from exc

            choice = completion.choices[0]
            msg = choice.message
            tool_calls = list(msg.tool_calls or [])
            if not tool_calls:
                # No tools needed — leave messages unchanged so the caller can
                # stream the final answer with stream=True (progressive SSE).
                return messages

            messages.append(self._assistant_tool_message(msg))
            for tc in tool_calls:
                name = tc.function.name
                args = tc.function.arguments or "{}"
                logger.info("DeepSeek tool call name=%s", name)
                result = await execute_chat_tool(name, args, session=session)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
        return messages

    async def _stream_completion(
        self,
        *,
        client: AsyncOpenAI,
        messages: list[dict[str, Any]],
    ) -> AsyncIterator[str]:
        """Yield text deltas as they arrive from DeepSeek (``stream=True``)."""
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
                    # Yield immediately — do not accumulate the full answer.
                    yield content
        except APITimeoutError as exc:
            logger.exception("DeepSeek stream timed out")
            raise TimeoutError("DeepSeek request timed out") from exc
        except RateLimitError as exc:
            logger.exception("DeepSeek rate limit exceeded")
            raise RuntimeError("DeepSeek rate limit exceeded") from exc
        except APIError as exc:
            logger.exception("DeepSeek API error: %s", exc)
            raise RuntimeError("DeepSeek API request failed") from exc

    async def stream_chat(
        self,
        *,
        message: str,
        conversation: Sequence[dict[str, Any]] | None = None,
        session: AsyncSession,
    ) -> AsyncIterator[str]:
        """Route via Function Calling when needed, then stream the final answer only."""
        client = self._get_client()
        messages = self.build_messages(message=message, conversation=conversation)
        messages = await self._run_tool_rounds(
            client=client, messages=messages, session=session
        )

        # Always stream the user-visible answer as DeepSeek deltas arrive.
        async for text in self._stream_completion(client=client, messages=messages):
            yield text


def get_deepseek_service(settings: Settings | None = None) -> DeepSeekService:
    return DeepSeekService(settings=settings)
