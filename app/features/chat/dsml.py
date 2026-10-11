"""Detect, parse, and suppress DeepSeek tool-call markup leaked into text content.

DeepSeek sometimes emits tool calls as raw DSML text in ``content`` instead of
structured ``tool_calls``, e.g.::

    <｜DSML｜function_calls>
    <｜DSML｜invoke name="search_shop_faq">
    <｜DSML｜parameter name="query" string="true">phí ship</｜DSML｜parameter>
    </｜DSML｜invoke>
    </｜DSML｜function_calls>

That markup must never reach users.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from uuid import uuid4

_BAR = r"[|｜]"

# Any opening/closing DSML tag or legacy ``<｜tool▁calls▁begin｜>`` marker.
_MARKER_RE = re.compile(rf"<\s*/?\s*{_BAR}+\s*(?:DSML|tool)", re.IGNORECASE)

# Trailing text that may still grow into a marker on the next chunk.
_PARTIAL_MARKER_RE = re.compile(rf"<\s*/?\s*({_BAR}*)\s*([A-Za-z]{{0,4}})")
_MARKER_WORDS = ("dsml", "tool")

_INVOKE_RE = re.compile(
    rf"<\s*{_BAR}+\s*DSML\s*{_BAR}+\s*invoke\s+name=\"([^\"]+)\"\s*>"
    rf"(.*?)"
    rf"(?:<\s*/\s*{_BAR}+\s*DSML\s*{_BAR}+\s*invoke\s*>|\Z)",
    re.DOTALL,
)
_PARAM_RE = re.compile(
    rf"<\s*{_BAR}+\s*DSML\s*{_BAR}+\s*parameter\s+name=\"([^\"]+)\""
    rf"(?:\s+string=\"(true|false)\")?\s*>"
    rf"(.*?)"
    rf"<\s*/\s*{_BAR}+\s*DSML\s*{_BAR}+\s*parameter\s*>",
    re.DOTALL,
)
_LEGACY_CALL_RE = re.compile(
    rf"<\s*{_BAR}+\s*tool▁call▁begin\s*{_BAR}+\s*>\s*(?:function)?\s*"
    rf"<\s*{_BAR}+\s*tool▁sep\s*{_BAR}+\s*>\s*([\w.-]+)\s*"
    rf"(?:```(?:json)?)?\s*(\{{.*?\}})\s*(?:```)?\s*"
    rf"<\s*{_BAR}+\s*tool▁call▁end",
    re.DOTALL,
)


@dataclass(frozen=True)
class ParsedToolCall:
    id: str
    name: str
    arguments: str


def new_tool_call_id() -> str:
    return f"call_{uuid4().hex[:16]}"


def contains_tool_markup(text: str | None) -> bool:
    return bool(text) and _MARKER_RE.search(text) is not None  # type: ignore[arg-type]


def strip_tool_markup(text: str | None) -> str:
    """Drop everything from the first tool-call marker onward."""
    if not text:
        return ""
    match = _MARKER_RE.search(text)
    return text if match is None else text[: match.start()]


def _parameter_value(raw: str, is_string: str | None) -> object:
    if is_string == "false":
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw.strip()
    return raw.strip()


def parse_dsml_tool_calls(text: str | None) -> list[ParsedToolCall]:
    """Extract tool calls from DSML (or legacy DeepSeek) markup text."""
    if not text:
        return []

    calls: list[ParsedToolCall] = []
    for invoke in _INVOKE_RE.finditer(text):
        name = invoke.group(1).strip()
        if not name:
            continue
        args = {
            param.group(1).strip(): _parameter_value(param.group(3), param.group(2))
            for param in _PARAM_RE.finditer(invoke.group(2))
        }
        calls.append(
            ParsedToolCall(
                id=new_tool_call_id(),
                name=name,
                arguments=json.dumps(args, ensure_ascii=False),
            )
        )
    if calls:
        return calls

    for legacy in _LEGACY_CALL_RE.finditer(text):
        try:
            args = json.loads(legacy.group(2))
        except json.JSONDecodeError:
            continue
        if isinstance(args, dict):
            calls.append(
                ParsedToolCall(
                    id=new_tool_call_id(),
                    name=legacy.group(1),
                    arguments=json.dumps(args, ensure_ascii=False),
                )
            )
    return calls


def _partial_marker_start(text: str) -> int | None:
    idx = text.rfind("<")
    if idx == -1:
        return None
    match = _PARTIAL_MARKER_RE.fullmatch(text, idx)
    if match is None:
        return None
    bars, word = match.group(1), match.group(2).lower()
    if word and (not bars or not any(w.startswith(word) for w in _MARKER_WORDS)):
        return None
    return idx


class DsmlStreamGuard:
    """Pass streamed text through, swallowing any tool-call markup.

    Once a marker is seen, that chunk's remainder and every later chunk are
    captured instead of emitted. A trailing partial marker is held back until
    the next chunk decides whether it is markup.
    """

    def __init__(self) -> None:
        self._pending = ""
        self._captured: list[str] = []
        self._capturing = False

    @property
    def captured(self) -> str:
        return "".join(self._captured)

    def feed(self, chunk: str) -> str:
        if self._capturing:
            self._captured.append(chunk)
            return ""

        text = self._pending + chunk
        self._pending = ""
        match = _MARKER_RE.search(text)
        if match is not None:
            self._capturing = True
            self._captured.append(text[match.start() :])
            return text[: match.start()]

        hold_from = _partial_marker_start(text)
        if hold_from is not None:
            self._pending = text[hold_from:]
            return text[:hold_from]
        return text

    def finish(self) -> str:
        pending, self._pending = self._pending, ""
        return "" if self._capturing else pending
