"""SSE frame encoding helpers for `ai-api` internal Tutor streaming."""

from __future__ import annotations

import json
from typing import Any

SSE_HEADERS = {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def frame(event: str, payload: dict[str, Any], *, event_id: str | None = None) -> str:
    """Encode a single-line JSON SSE frame terminated by a blank line."""
    lines: list[str] = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    lines.append(f"data: {data}")
    return "\n".join(lines) + "\n\n"
