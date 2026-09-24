"""Server-Sent Events helpers for streaming API responses."""

from __future__ import annotations

import json
from typing import Any


def sse_json(payload: dict[str, Any]) -> str:
    """Encode one SSE ``data:`` frame with a JSON object body."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def sse_chunk(content: str) -> str:
    """Stream a text delta from the model."""
    return sse_json({"type": "chunk", "content": content})


def sse_error(message: str) -> str:
    """Stream a client-visible error without closing as a bare HTTP failure mid-stream."""
    return sse_json({"type": "error", "message": message})


def sse_done() -> str:
    """Mark the stream as complete."""
    return sse_json({"type": "done"})
