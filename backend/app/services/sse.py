"""SSE encoding helpers (P3.0) — một nơi duy nhất để frame đúng chuẩn.

Lý do tách: SSE rất dễ hỏng theo cách âm thầm (newline trong `data:` làm client
hiểu sai, chunk không flush, `no-store` thiếu ⇒ proxy cache nội dung cá nhân).
Các helper ở đây được test trực tiếp, không phụ thuộc FastAPI.

Định dạng mỗi frame:

    id: <event id>
    event: <delta|done|error|heartbeat>
    data: <json 1 dòng>

Mọi ký tự xuống dòng trong JSON được escape nên `data:` luôn là một dòng.
"""

from __future__ import annotations

import json
from typing import Any

SSE_HEADERS = {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Connection": "keep-alive",
    # Chặn proxy buffer (nginx) làm stream "đứng" tới khi kết thúc.
    "X-Accel-Buffering": "no",
}


def frame(event: str, payload: dict[str, Any], *, event_id: str | None = None) -> str:
    """Một frame SSE hoàn chỉnh (kết thúc bằng dòng trống)."""
    lines: list[str] = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    # ensure_ascii=False giữ tiếng Việt đọc được; separators bỏ khoảng trắng thừa.
    # json.dumps không sinh newline thật, nên payload luôn nằm trên 1 dòng data:.
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    lines.append(f"data: {data}")
    return "\n".join(lines) + "\n\n"


def seq_id(stream_id: str, seq: int) -> str:
    return f"{stream_id}:{seq}"
