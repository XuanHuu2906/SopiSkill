"""AI Tutor tools (P3.1 lat B) — allowlist server-side, read-only, co audit.

Quyet dinh thiet ke (xem `docs/specs/17-DECISION-LOG.md`): dung **server-side
deterministic tools** thay vi native `tool_calls` cua provider.

Ly do:
  - Mock provider phai chay duoc cung contract, khong can goi API tra phi.
  - Moi thu model "yeu cau" deu duoc validate lai o server: ten tool phai nam
    trong allowlist, arguments phai dung schema (`extra=forbid`), index phai nam
    trong bien **public blocks** cua chinh lesson ma course so huu.
  - Khong co tool nao ghi du lieu, khong tool nao truy cap mang, khong doc
    answer key hay noi dung course khac.

Luong: model tra JSON `{"tool": <name>, "args": {...}}` qua hook
`plan_tutor_tool`; server parse -> validate -> execute -> ghi audit. Sau toi da
`TUTOR_TOOL_MAX_CALLS` lan, ket qua (da cat ky tu) duoc dua vao prompt nhu
**du lieu khong tin cay** de model viet cau tra loi cuoi.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.services import tutor_context

logger = logging.getLogger(__name__)

TOOL_NOT_ALLOWED = "TUTOR_TOOL_NOT_ALLOWED"
TOOL_INVALID_ARGS = "TUTOR_TOOL_INVALID_ARGS"
TOOL_LIMIT_REACHED = "TUTOR_TOOL_LIMIT_REACHED"
TOOL_TIMEOUT = "TUTOR_TOOL_TIMEOUT"
TOOL_NOT_AVAILABLE = "TUTOR_TOOL_NOT_AVAILABLE"
TOOL_FAILED = "TUTOR_TOOL_FAILED"

# Dung list + "\n".join de tranh escape trong chuoi literal.
TOOL_PLANNER_SYSTEM_LINES = [
    "Bạn là bộ lập kế hoạch cho trợ giảng AI trong một nền tảng học tập.",
    "Chỉ được chọn MỘT trong các tool sau (hoặc không dùng tool):",
    "- read_lesson: đọc lại nội dung bài học hiện tại. args: {} hoặc "
    '{"blockIndex": <int>}.',
    "- explain_deeper: mở rộng giải thích cho một block. args: "
    '{"blockIndex": <int>}.',
    "- read_source: đọc nguồn tài liệu đã ingest. args: {}. "
    "(P3.1 CHƯA có dữ liệu nguồn nên tool này sẽ từ chối; chỉ chọn khi "
    "người học hỏi cần dẫn nguồn.)",
    "Quy tắc: chỉ chọn tool khi thực sự cần thêm ngữ cảnh để trả lời câu hỏi.",
    "Không bao giờ bịa tên tool khác. Trả JSON đúng một object, ví dụ "
    '{"tool": "read_lesson", "args": {"blockIndex": 2}} hoặc '
    '{"tool": null, "args": {}}.',
    "Không markdown, không giải thích.",
]
TOOL_PLANNER_SYSTEM = "\n".join(TOOL_PLANNER_SYSTEM_LINES)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    available: bool
    summary_label: str


# Allowlist DUY NHAT. Ten la -> tu choi truoc khi toi executor.
TOOLS: dict[str, ToolSpec] = {
    "read_lesson": ToolSpec("read_lesson", True, "đọc bài học"),
    "explain_deeper": ToolSpec("explain_deeper", True, "mở rộng giải thích"),
    # P3.1.3: chi bat that sau P4.1 (chunk ownership + provenance). Hien tai duoc
    # allowlist de cau tu choi huu ich thay vi "tool khong ton tai".
    "read_source": ToolSpec("read_source", False, "đọc nguồn tài liệu"),
}


class ReadLessonArgs(BaseModel):
    blockIndex: int | None = Field(default=None, ge=0, le=200)
    model_config = {"extra": "forbid"}


class ExplainDeeperArgs(BaseModel):
    blockIndex: int = Field(ge=0, le=200)
    model_config = {"extra": "forbid"}


class ReadSourceArgs(BaseModel):
    model_config = {"extra": "forbid"}


ARG_MODELS: dict[str, type[BaseModel]] = {
    "read_lesson": ReadLessonArgs,
    "explain_deeper": ExplainDeeperArgs,
    "read_source": ReadSourceArgs,
}


class ToolRequestError(Exception):
    """Yeu cau tool bi tu choi — luon kem ma loi on dinh de audit."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ToolExecution:
    name: str
    ok: bool
    duration_ms: int
    summary: str
    error_code: str | None = None
    # Noi dung dua vao prompt (da cat ky tu). KHONG luu DB.
    content: str = ""
    args_summary: str = ""


@dataclass
class ToolLoopResult:
    executions: list[ToolExecution] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.executions)

    def prompt_section(self, max_chars: int) -> str:
        return tutor_context.build_tool_results_section(
            [
                {
                    "name": execution.name,
                    "ok": execution.ok,
                    "summary": execution.summary,
                    "errorCode": execution.error_code,
                    "content": execution.content,
                }
                for execution in self.executions
            ],
            max_chars=max_chars,
        )


def parse_tool_request(raw: Any) -> tuple[str | None, dict]:
    """Chuan hoa output cua planner thanh (ten tool | None, args).

    Chap nhan dict da parse hoac chuoi JSON (co the boc ```json). Khong bao gio
    "doan" tool tu text tu do: neu khong phai JSON hop le => coi nhu khong dung tool.
    """
    data: Any = raw
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        if not text:
            return None, {}
        try:
            data = json.loads(text)
        except ValueError:
            return None, {}
    if not isinstance(data, dict):
        return None, {}
    name = data.get("tool")
    args = data.get("args", {})
    if name in (None, "", "none", "None"):
        return None, {}
    # `args` phải là dict: list/string là output sai định dạng, không được "sửa"
    # thành {} rồi chạy tool với tham số mặc định.
    if not isinstance(name, str) or not isinstance(args, dict):
        return None, {}
    return name.strip(), args


def validate_request(name: str, args: dict, *, block_count: int) -> BaseModel:
    """Validate ten + arguments TRUOC khi execute. Raise ToolRequestError."""
    spec = TOOLS.get(name)
    if spec is None:
        raise ToolRequestError(
            TOOL_NOT_ALLOWED, f"Tool '{name}' không nằm trong allowlist."
        )
    model = ARG_MODELS[name]
    try:
        parsed = model.model_validate(args)
    except ValidationError as exc:
        # Khong lo toan bo chi tiet Pydantic ra ngoai log/response.
        first = exc.errors()[0] if exc.errors() else {}
        raise ToolRequestError(
            TOOL_INVALID_ARGS,
            f"Arguments của tool '{name}' không hợp lệ "
            f"({first.get('loc', '?')}: {first.get('type', 'invalid')}).",
        ) from exc

    if name in ("read_lesson", "explain_deeper"):
        index = getattr(parsed, "blockIndex", None)
        if index is not None and index >= block_count:
            raise ToolRequestError(
                TOOL_INVALID_ARGS,
                f"blockIndex {index} vượt quá số block của bài ({block_count}).",
            )
    return parsed


def _args_summary(name: str, parsed: BaseModel) -> str:
    """Mo ta ngan, khong chua noi dung nguoi hoc hay du lieu nhay cam."""
    index = getattr(parsed, "blockIndex", None)
    if index is None:
        return f"{name}()"
    return f"{name}(blockIndex={index})"


def execute(
    name: str,
    parsed: BaseModel,
    *,
    blocks: list[dict],
    current_block_index: int,
    max_chars: int,
) -> ToolExecution:
    """Chay tool read-only. Khong co side-effect, khong truy cap mang/DB."""
    started = time.perf_counter()
    spec = TOOLS[name]

    if not spec.available:
        return ToolExecution(
            name=name,
            ok=False,
            duration_ms=int((time.perf_counter() - started) * 1000),
            summary=f"{spec.summary_label}: chưa khả dụng ở P3.1",
            error_code=TOOL_NOT_AVAILABLE,
            content="",
            args_summary=_args_summary(name, parsed),
        )

    try:
        if name == "read_lesson":
            index = getattr(parsed, "blockIndex", None)
            if index is None:
                content = "\n\n".join(
                    f"#{i} {tutor_context.block_digest(block, 500)}"
                    for i, block in enumerate(blocks)
                )
                summary = f"đọc {len(blocks)} block của bài"
            else:
                content = f"#{index} {tutor_context.block_digest(blocks[index], 800)}"
                summary = f"đọc block #{index}"
        elif name == "explain_deeper":
            index = getattr(parsed, "blockIndex", current_block_index)
            current = blocks[index]
            neighbours = [
                f"#{i} {tutor_context.block_digest(block, 500)}"
                for i, block in enumerate(blocks)
                if i != index and block.get("type") == "teach"
            ][:3]
            parts = [
                f"Block cần giải thích:\n#{index} "
                f"{tutor_context.block_digest(current, 800)}"
            ]
            if neighbours:
                parts.append("Đoạn giảng liên quan:\n" + "\n".join(neighbours))
            content = "\n\n".join(parts)
            summary = (
                f"mở rộng block #{index} "
                f"({tutor_context.BLOCK_LABELS.get(current.get('type'), '?')})"
            )
        else:  # pragma: no cover — allowlist chan truoc
            raise ToolRequestError(TOOL_NOT_ALLOWED, f"Tool '{name}' không hỗ trợ.")
    except ToolRequestError as exc:
        return ToolExecution(
            name=name,
            ok=False,
            duration_ms=int((time.perf_counter() - started) * 1000),
            summary=exc.message,
            error_code=exc.code,
            args_summary=_args_summary(name, parsed),
        )
    except Exception:  # noqa: BLE001 — tool loi khong duoc lam chet luot hoi
        logger.warning("tutor tool failed tool=%s", name)
        return ToolExecution(
            name=name,
            ok=False,
            duration_ms=int((time.perf_counter() - started) * 1000),
            summary="Tool gặp lỗi khi thực thi.",
            error_code=TOOL_FAILED,
            args_summary=_args_summary(name, parsed),
        )

    return ToolExecution(
        name=name,
        ok=True,
        duration_ms=int((time.perf_counter() - started) * 1000),
        summary=summary,
        content=content[: max(0, max_chars)],
        args_summary=_args_summary(name, parsed),
    )


def audit_summary(execution: ToolExecution) -> str:
    """Chuoi audit an toan de luu DB (khong chua noi dung bai/nguoi hoc)."""
    text = (
        f"{execution.args_summary} -> "
        f"{'ok' if execution.ok else 'fail'}: {execution.summary}"
    )
    return text[:400]
