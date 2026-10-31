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

import logging
from dataclasses import dataclass, field

from app.providers.base import LLMProvider, ProviderError
from evals.rubric import HUMAN_RUBRIC

logger = logging.getLogger(__name__)

JUDGE_PROMPT_VERSION = "p2.2-judge-v1"

JUDGE_SYSTEM = (
    "Bạn là chuyên gia đánh giá chất lượng chương trình học. Bạn KHÔNG phải người "
    "học và không được khen ngợi chung chung. Chấm khách quan, nêu bằng chứng "
    "ngắn trong trường 'evidence'. Nếu không đủ thông tin để chấm một tiêu chí, "
    "trả score = null cho tiêu chí đó thay vì đoán. Trả JSON object với khóa "
    "'scores' là object {criterionId: 0..4 hoặc null} và 'notes' là mảng chuỗi "
    "ngắn (tối đa 5). Không trả markdown, không giải thích ngoài JSON."
)

MAX_JUDGE_CHARS = 16_000


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
    *, topic: str, language: str, level: str, proposal: dict, lessons: list[dict]
) -> str:
    """Dựng prompt judge. Nội dung lesson đã là văn bản công khai của course."""
    criteria = _criteria_payload()
    lines = [
        f"Chủ đề: {topic}",
        f"Ngôn ngữ yêu cầu: {language}; trình độ người học: {level}",
        "Tiêu chí chấm (score 0..4): "
        + "; ".join(f"{c['id']} = {c['label']}" for c in criteria),
        "",
        "PROPOSAL:",
        str(proposal)[:6000],
        "",
        "BÀI HỌC:",
    ]
    for index, lesson in enumerate(lessons, start=1):
        lines.append(f"--- Bài {index} ---")
        lines.append(str(lesson)[:3000])
    text = "\n".join(lines)
    return text[:MAX_JUDGE_CHARS]


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
