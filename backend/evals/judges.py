"""P2.2 LLM-as-judge — tín hiệu tham khảo, KHÔNG phải ground truth.

Vì sao tách riêng:

  - Điểm deterministic (`rubric.py`) là cổng fail/ pass duy nhất.
  - Judge chỉ bổ sung nhận xét định tính ("mục tiêu có rõ không", "ví dụ có
    đúng chuyên môn không"). Nó **không** được dùng thay cho người chấm, và mọi
    kết quả đều lưu `judgeModel`, `judgePromptVersion`, `usedLlm` để truy vết.
  - Judge gửi nội dung sinh ra (không phải dữ liệu người học) tới provider; chỉ
    chạy khi người dùng đã duyệt ngân sách/real provider.

Nếu provider không hỗ trợ lời gọi JSON (mock), kết quả là `status="not_run"`
chứ **không** phải điểm 0/điểm giả.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from app.providers.base import LLMProvider, ProviderError
from evals.rubric import HUMAN_RUBRIC

logger = logging.getLogger(__name__)

JUDGE_PROMPT_VERSION = "p2.2-judge-v2"

JUDGE_SYSTEM = (
    "Bạn là chuyên gia đánh giá chất lượng chương trình học. Bạn KHÔNG phải người "
    "học và không được khen ngợi chung chung. Chấm khách quan, ngắn gọn, nêu bằng "
    "chứng súc tích trong mảng 'notes'. Nếu không đủ thông tin để chấm một tiêu "
    "chí, trả score = null cho tiêu chí đó thay vì đoán. Lưu ý: nếu prompt ghi "
    "chỉ hiển thị K/N bài tiêu biểu để vừa ngân sách ngữ cảnh thì các bài chưa "
    "hiển thị KHÔNG phải lỗi cắt cụt — chỉ chấm cắt cụt nếu bên trong một bài "
    "được hiển thị có câu/code bị đứt dở. Trả JSON object thuần với khóa "
    "'scores' là object {criterionId: 0..4 hoặc null} và 'notes' là mảng tối đa "
    "5 chuỗi ngắn (mỗi chuỗi <= 180 ký tự). Giữ suy luận thật ngắn gọn; không "
    "trả markdown, không giải thích ngoài JSON."
)

MAX_JUDGE_CHARS = 32_000


def _compact_json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _format_proposal_for_judge(proposal: dict, budget: int) -> str:
    raw = _compact_json(proposal)
    if len(raw) <= budget:
        return raw
    # Nếu proposal quá lớn, rút gọn theo cấu trúc hợp lệ (không cắt ngang JSON).
    units = proposal.get("units") if isinstance(proposal, dict) else None
    compact_units = []
    if isinstance(units, list):
        for u in units:
            if isinstance(u, dict):
                compact_units.append(
                    {
                        "title": u.get("title"),
                        "lessonTitles": u.get("lessonTitles"),
                    }
                )
    slim = {
        "name": proposal.get("name") if isinstance(proposal, dict) else None,
        "objective": proposal.get("objective") if isinstance(proposal, dict) else None,
        "learnerProfile": proposal.get("learnerProfile") if isinstance(proposal, dict) else None,
        "units": compact_units,
        "outcomes": (proposal.get("outcomes") or [])[:4] if isinstance(proposal, dict) else [],
    }
    slim_raw = _compact_json(slim)
    if len(slim_raw) <= budget:
        return slim_raw
    return _compact_json({"name": slim.get("name"), "units": compact_units})[:budget]


def _select_whole_lessons(
    rendered_lessons: list[tuple[int, str]], budget: int
) -> list[tuple[int, str]]:
    """Chọn các bài học NGUYÊN VẸN nằm gọn trong budget, không bao giờ cắt giữa bài.

    Nếu tất cả bài học vừa budget thì giữ đủ 100%. Nếu vượt budget thì lấy bài
    đầu, bài cuối và các bài phân bố đều ở giữa để judge thấy toàn bộ tiến trình
    khóa học mà không thấy bài nào bị cắt cụt giả.
    """
    if not rendered_lessons or budget <= 0:
        return []

    total_len = sum(len(chunk) + 1 for _, chunk in rendered_lessons)
    if total_len <= budget:
        return list(rendered_lessons)

    n = len(rendered_lessons)
    # Thứ tự ưu tiên cân bằng: bài đầu, bài cuối, bài giữa, rồi phần còn lại.
    priority: list[int] = []
    if n >= 1:
        priority.append(0)
    if n >= 2:
        priority.append(n - 1)
    if n >= 3:
        mid = n // 2
        if mid not in priority:
            priority.append(mid)
    for i in range(n):
        if i not in priority:
            priority.append(i)

    chosen_indices: list[int] = []
    used = 0
    for idx in priority:
        chunk_len = len(rendered_lessons[idx][1]) + 1
        if used + chunk_len <= budget:
            chosen_indices.append(idx)
            used += chunk_len

    chosen_indices.sort()
    return [rendered_lessons[i] for i in chosen_indices]


@dataclass
class JudgeResult:
    status: str  # "scored" | "not_run" | "error"
    usedLlm: bool = False
    judgeModel: str | None = None
    promptVersion: str = JUDGE_PROMPT_VERSION
    scores: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    averageScore: float | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "usedLlm": self.usedLlm,
            "judgeModel": self.judgeModel,
            "promptVersion": self.promptVersion,
            "scores": self.scores,
            "notes": self.notes,
            "averageScore": self.averageScore,
            "error": self.error,
            "disclaimer": (
                "Điểm do LLM chấm chỉ là tín hiệu tham khảo, không phải ground "
                "truth và không thay thế người chấm."
            ),
        }


def _criteria_payload() -> list[dict]:
    criteria, _scale, _note = HUMAN_RUBRIC
    return [dict(item) for item in criteria]


def build_judge_user_message(
    *,
    topic: str,
    language: str,
    level: str,
    proposal: dict,
    lessons: list[dict],
    max_chars: int = MAX_JUDGE_CHARS,
) -> str:
    """Dựng prompt judge với các bài học nguyên vẹn (không cắt ngang giữa bài)."""
    criteria = _criteria_payload()
    proposal_budget = max(800, min(6000, max_chars // 4))
    header_lines = [
        f"Chủ đề: {topic}",
        f"Ngôn ngữ yêu cầu: {language}; trình độ người học: {level}",
        "Tiêu chí chấm (score 0..4): "
        + "; ".join(f"{c['id']} = {c['label']}" for c in criteria),
        "",
        "PROPOSAL:",
        _format_proposal_for_judge(proposal, proposal_budget),
        "",
    ]
    header_text = "\n".join(header_lines)

    total = len(lessons)
    rendered_lessons = [
        (index, f"--- Bài {index}/{total} ---\n{_compact_json(lesson)}")
        for index, lesson in enumerate(lessons, start=1)
    ]

    # Chừa khoảng an toàn cho dòng tiêu đề mục BÀI HỌC (kể cả ghi chú K/N bài).
    section_reserve = 220
    lessons_budget = max(0, max_chars - len(header_text) - section_reserve)
    selected = _select_whole_lessons(rendered_lessons, lessons_budget)

    if total == 0:
        section_header = "BÀI HỌC (0/0 bài):"
    elif len(selected) == total:
        section_header = f"BÀI HỌC (đầy đủ {total}/{total} bài, không cắt ngang):"
    else:
        shown_list = ", ".join(str(idx) for idx, _ in selected) or "không có"
        section_header = (
            f"BÀI HỌC (hiển thị đầy đủ {len(selected)}/{total} bài tiêu biểu: "
            f"[{shown_list}]; các bài còn lại được lược bỏ có chủ đích để vừa "
            "ngân sách ngữ cảnh, KHÔNG coi là lỗi cắt cụt):"
        )

    parts = [header_text, section_header]
    parts.extend(chunk for _, chunk in selected)
    return "\n".join(parts)


def _scores_from(data: dict) -> tuple[dict, list[str], float | None]:
    raw_scores = data.get("scores")
    clean: dict = {}
    if isinstance(raw_scores, dict):
        allowed = {c["id"] for c in _criteria_payload()}
        for key, value in raw_scores.items():
            if key not in allowed:
                continue
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)) and 0 <= float(value) <= 4:
                clean[key] = float(value)
            else:
                clean[key] = None
    notes = [str(n)[:300] for n in (data.get("notes") or []) if str(n).strip()][:5]
    numeric = [v for v in clean.values() if isinstance(v, (int, float))]
    average = round(sum(numeric) / len(numeric), 2) if numeric else None
    return clean, notes, average


async def judge_course(
    provider: LLMProvider,
    *,
    topic: str,
    language: str,
    level: str,
    proposal: dict,
    lessons: list[dict],
    model: str | None = None,
) -> JudgeResult:
    """Chấm 1 course bằng LLM. Lỗi provider ⇒ status='error' (không bịa điểm)."""
    user = build_judge_user_message(
        topic=topic,
        language=language,
        level=level,
        proposal=proposal,
        lessons=lessons,
    )
    try:
        data = await provider.request_json(
            system=JUDGE_SYSTEM, user=user, max_input_chars=MAX_JUDGE_CHARS
        )
    except ProviderError as exc:
        # Mock/không hỗ trợ/không cấu hình: KHÔNG giả vờ đã chấm.
        logger.info("judge not run provider=%s code=%s", provider.name, exc.code)
        status = "not_run" if exc.code == "PROVIDER_NOT_CONFIGURED" else "error"
        return JudgeResult(status=status, error=f"{exc.code}: {str(exc)[:160]}")
    except Exception as exc:  # noqa: BLE001 — judge không được làm hỏng eval
        logger.warning("judge failed provider=%s error=%s", provider.name, type(exc).__name__)
        return JudgeResult(status="error", error=type(exc).__name__)

    scores, notes, average = _scores_from(data if isinstance(data, dict) else {})
    return JudgeResult(
        status="scored",
        usedLlm=True,
        judgeModel=model or getattr(provider, "model", None),
        scores=scores,
        notes=notes,
        averageScore=average,
    )
