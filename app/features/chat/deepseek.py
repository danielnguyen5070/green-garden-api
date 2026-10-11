"""DeepSeek chat client with Function Calling routing (OpenAI-compatible SDK)."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from openai import APIError, APITimeoutError, AsyncOpenAI, RateLimitError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.features.chat.dsml import (
    DsmlStreamGuard,
    ParsedToolCall,
    contains_tool_markup,
    new_tool_call_id,
    parse_dsml_tool_calls,
    strip_tool_markup,
)
from app.features.chat.tools import CHAT_TOOLS, execute_chat_tool

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
- Shop and buying questions (where to buy, Cái Mơn seedling quality, ordering, \
delivery time, shipping cost, shipping to provinces, packing, payment / COD, \
tracking, returns, damaged plants, first steps after receiving plants, time to \
fruit) → call search_shop_faq. For general care questions, you may call both \
search_shop_faq and search_plant_knowledge.
- Answer shop policy questions only from search_shop_faq results. If nothing \
relevant is found, say so and suggest messaging the shop on Zalo 0386569374.
- Greetings and general chat with no catalogue need → answer directly (no tools).
- If a question needs both business data and knowledge, call multiple tools.

Never mention tools, function calls, databases, Weaviate, RAG, or implementation details.\
"""

ALLOWED_ROLES = frozenset({"system", "user", "assistant"})
MAX_TOOL_ROUNDS = 3
MAX_STREAM_TOOL_ROUNDS = 2

FALLBACK_REPLY = (
    "Xin lỗi, mình chưa tìm được thông tin phù hợp. "
    "Bạn vui lòng nhắn Zalo 0386569374 để shop hỗ trợ nhé. / "
    "Sorry, I couldn't find that information. "
    "Please message the shop on Zalo 0386569374."
)


class DeepSeekNotConfiguredError(RuntimeError):
    """Raised when DEEPSEEK_API_KEY is missing."""


@dataclass
class _StreamRoundResult:
    text: str = ""
    markup: str = ""
    tool_calls: list[ParsedToolCall] = field(default_factory=list)


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
            if role == "assistant":
                # Leaked markup in history primes the model to leak again.
                content = strip_tool_markup(content).strip()
            if role not in ALLOWED_ROLES or role == "system" or not content:
                continue
            messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": message.strip()})
        return messages

    @staticmethod
    def _native_tool_calls(raw_calls: Sequence[Any] | None) -> list[ParsedToolCall]:
        calls: list[ParsedToolCall] = []
        for tc in raw_calls or []:
            function = getattr(tc, "function", None)
            name = getattr(function, "name", None) if function is not None else None
            if not name:
                continue
            calls.append(
                ParsedToolCall(
                    id=getattr(tc, "id", None) or new_tool_call_id(),
                    name=name,
                    arguments=getattr(function, "arguments", None) or "{}",
                )
            )
        return calls

    async def _execute_tool_calls(
        self,
        *,
        messages: list[dict[str, Any]],
        calls: Sequence[ParsedToolCall],
        content: str | None,
        session: AsyncSession,
    ) -> None:
        """Append the assistant tool-call turn and each tool result to ``messages``."""
        messages.append(
            {
                "role": "assistant",
                "content": strip_tool_markup(content).strip() or None,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                    for call in calls
                ],
            }
        )
        for call in calls:
            logger.info("DeepSeek tool call name=%s", call.name)
            result = await execute_chat_tool(call.name, call.arguments, session=session)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

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

            msg = completion.choices[0].message
            content = getattr(msg, "content", None)
            calls = self._native_tool_calls(getattr(msg, "tool_calls", None))
            if not calls and contains_tool_markup(content):
                calls = parse_dsml_tool_calls(content)
                if not calls:
                    logger.warning("Unparseable tool-call markup in routing reply")
            if not calls:
                # No tools needed — leave messages unchanged so the caller can
                # stream the final answer with stream=True (progressive SSE).
                return messages

            await self._execute_tool_calls(
                messages=messages, calls=calls, content=content, session=session
            )
        return messages

    async def _stream_completion(
        self,
        *,
        client: AsyncOpenAI,
        messages: list[dict[str, Any]],
        result: _StreamRoundResult,
    ) -> AsyncIterator[str]:
        """Yield safe text deltas as they arrive; collect any tool calls into ``result``."""
        guard = DsmlStreamGuard()
        partial_calls: dict[int, dict[str, str]] = {}
        try:
            stream = await client.chat.completions.create(
                model=self._settings.deepseek_model,
                messages=messages,  # type: ignore[arg-type]
                tools=CHAT_TOOLS,  # type: ignore[arg-type]
                tool_choice="auto",
                stream=True,
            )
            async for chunk in stream:
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                if delta is None:
                    continue

                for tc in getattr(delta, "tool_calls", None) or []:
                    index = getattr(tc, "index", None)
                    if index is None:
                        index = len(partial_calls)
                    entry = partial_calls.setdefault(
                        index, {"id": "", "name": "", "arguments": ""}
                    )
                    if getattr(tc, "id", None):
                        entry["id"] = tc.id
                    function = getattr(tc, "function", None)
                    if function is not None:
                        if getattr(function, "name", None):
                            entry["name"] = function.name
                        entry["arguments"] += getattr(function, "arguments", None) or ""

                content = getattr(delta, "content", None)
                if content:
                    safe = guard.feed(content)
                    if safe:
                        result.text += safe
                        # Yield immediately — do not accumulate the full answer.
                        yield safe

            tail = guard.finish()
            if tail:
                result.text += tail
                yield tail
        except APITimeoutError as exc:
            logger.exception("DeepSeek stream timed out")
            raise TimeoutError("DeepSeek request timed out") from exc
        except RateLimitError as exc:
            logger.exception("DeepSeek rate limit exceeded")
            raise RuntimeError("DeepSeek rate limit exceeded") from exc
        except APIError as exc:
            logger.exception("DeepSeek API error: %s", exc)
            raise RuntimeError("DeepSeek API request failed") from exc

        result.markup = guard.captured
        result.tool_calls = [
            ParsedToolCall(
                id=entry["id"] or new_tool_call_id(),
                name=entry["name"],
                arguments=entry["arguments"] or "{}",
            )
            for _, entry in sorted(partial_calls.items())
            if entry["name"]
        ]

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

        emitted = False
        suppressed = False
        for round_no in range(MAX_STREAM_TOOL_ROUNDS + 1):
            result = _StreamRoundResult()
            async for text in self._stream_completion(
                client=client, messages=messages, result=result
            ):
                emitted = True
                yield text

            calls = result.tool_calls or parse_dsml_tool_calls(result.markup)
            if not calls:
                if result.markup:
                    logger.warning("Suppressed unparseable tool-call markup in stream")
                    suppressed = True
                break
            if round_no == MAX_STREAM_TOOL_ROUNDS:
                logger.warning("DeepSeek still requesting tools after max stream rounds")
                suppressed = True
                break

            await self._execute_tool_calls(
                messages=messages, calls=calls, content=result.text, session=session
            )

        if suppressed and not emitted:
            yield FALLBACK_REPLY


def get_deepseek_service(settings: Settings | None = None) -> DeepSeekService:
    return DeepSeekService(settings=settings)
