"""P2.1 real-provider evaluation (opt-in, tốn phí — KHÔNG chạy trong pytest).

Mục đích: lấy bằng chứng cho P2.1.8 bằng **request thật** tới provider đã được
người dùng duyệt (mặc định là cấu hình trong `.env`), đo:

  - tỉ lệ output qua Pydantic + semantic lint (schema pass rate)
  - curriculum DAG hợp lệ cho từng topic
  - bài học có teach + quiz, không lặp câu hỏi/đoạn giảng
  - thời gian (latency) và token thực tế theo từng lời gọi

Cách chạy:

    cd backend
    set LLM_PROVIDER=openai            # hoặc openai_compatible
    python -m evals.real_provider_eval --topics 3

An toàn:
  - Không log prompt/answer của người học; chỉ log metadata (topic id, token).
  - Không ghi API key vào report.
  - Mặc định chỉ chạy khi có `--yes` để không vô tình đốt tiền trong CI.

Kết quả JSON nằm ở `backend/evals/reports/` (gitignored).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import pathlib
import sys
import time
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.providers import ProviderConfigError, get_provider
from app.providers.openai_compatible_provider import PROMPT_VERSION
from app.schemas.schemas import ProposalPayload
from app.services import pedagogy

REPORT_DIR = pathlib.Path(__file__).parent / "reports"

# Windows console mặc định cp1258/cp1252 → in tiếng Việt/mũi tên sẽ nổ UnicodeEncodeError.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except (AttributeError, OSError):  # pragma: no cover — console không hỗ trợ
    pass

TOPICS: list[dict] = [
    {
        "id": "vi-beginner-tech",
        "topic": "Python cho người mới bắt đầu",
        "answers": [
            "Mình chưa từng học Python",
            "Muốn tự viết được script xử lý file Excel cho công việc",
            "Mỗi tuần khoảng 4 giờ",
            "Thích thực hành và làm bài tập nhỏ",
            "Muốn nắm nền tảng thật chắc trước khi đi sâu",
        ],
    },
    {
        "id": "vi-advanced-social",
        "topic": "Kinh tế học hành vi ứng dụng trong thiết kế sản phẩm",
        "answers": [
            "Mình đã có nhiều năm kinh nghiệm làm product",
            "Muốn áp dụng thiên lệch nhận thức vào onboarding để tăng retention",
            "2 giờ mỗi tuần",
            "Thích đọc nghiên cứu kèm ví dụ thực tế",
            "Muốn đi sâu vào các mô hình và bằng chứng",
        ],
    },
    {
        "id": "en-advanced-eng",
        "topic": "Distributed systems consistency models",
        "answers": [
            "I have several years of backend experience with highly available services",
            "I want to reason correctly about trade-offs when designing a new data store",
            "about 5 hours per week",
            "hands-on with failure scenarios and code labs",
            "deep dive into proofs and real production incidents",
        ],
    },
]


@dataclass
class TokenCounter(logging.Handler):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0

    def __post_init__(self) -> None:
        # logging.Handler không phải dataclass → phải tự khởi tạo, nếu không
        # `self.level`/lock không tồn tại và logger.addHandler sẽ nổ AttributeError.
        logging.Handler.__init__(self, level=logging.INFO)

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if "llm call ok" not in message:
            return
        self.calls += 1
        for part in message.split():
            if part.startswith("prompt_tokens="):
                try:
                    self.prompt_tokens += int(part.split("=", 1)[1])
                except ValueError:
                    pass
            elif part.startswith("completion_tokens="):
                try:
                    self.completion_tokens += int(part.split("=", 1)[1])
                except ValueError:
                    pass


@dataclass
class TopicResult:
    id: str
    topic: str
    provider: str
    model: str
    prompt_version: str = PROMPT_VERSION
    interview_ok: bool = False
    proposal_ok: bool = False
    curriculum_ok: bool = False
    lessons_total: int = 0
    lessons_ok: int = 0
    lesson_failures: list[str] = field(default_factory=list)
    unique_lesson_titles: bool = False
    skills: int = 0
    edges: int = 0
    bloom_levels: list[str] = field(default_factory=list)
    latency_seconds: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_calls: int = 0
    error: str | None = None

    @property
    def passed(self) -> bool:
        return (
            self.interview_ok
            and self.proposal_ok
            and self.curriculum_ok
            and self.lessons_total > 0
            and self.lessons_ok == self.lessons_total
            and self.error is None
        )

    def to_dict(self) -> dict:
        data = self.__dict__.copy()
        data["passed"] = self.passed
        return data


async def evaluate_topic(provider, spec: dict) -> TopicResult:
    settings = get_settings()
    result = TopicResult(
        id=spec["id"], topic=spec["topic"], provider=provider.name, model=settings.llm_model
    )
    counter = TokenCounter()
    adapter_logger = logging.getLogger("app.providers.openai_compatible_provider")
    # Logger mặc định kế thừa level WARNING từ root → record INFO (chứa token usage)
    # bị drop trước khi tới handler. Hạ level trong phạm vi eval rồi khôi phục.
    previous_level = adapter_logger.level
    adapter_logger.setLevel(logging.INFO)
    adapter_logger.addHandler(counter)
    started = time.perf_counter()
    try:
        questions = await provider.generate_interview_questions(spec["topic"])
        result.interview_ok = len(questions) == 5

        payload: ProposalPayload = await provider.generate_proposal(
            spec["topic"], questions, spec["answers"]
        )
        payload.learnerProfile = pedagogy.extract_learner_profile(questions, spec["answers"])
        payload = pedagogy.normalize_curriculum(payload)
        pedagogy.validate_curriculum(payload)
        result.proposal_ok = True
        result.curriculum_ok = True

        titles = pedagogy.lesson_order(payload)
        result.lessons_total = len(titles)
        result.unique_lesson_titles = len({t.strip().casefold() for t in titles}) == len(titles)
        result.skills = len(payload.skills)
        result.edges = len(payload.prerequisites)
        result.bloom_levels = sorted({s.bloomLevel for s in payload.skills})

        previous: list[str] = []
        for unit in payload.units:
            for title in unit.lessonTitles:
                try:
                    lesson = await provider.generate_lesson(
                        spec["topic"], payload, unit.title, title, previous
                    )
                except Exception as exc:  # noqa: BLE001 — ghi lại từng bài lỗi
                    result.lesson_failures.append(f"{title}: {type(exc).__name__}: {str(exc)[:160]}")
                    continue
                result.lessons_ok += 1
                previous.append(lesson.title)
    except Exception as exc:  # noqa: BLE001
        result.error = f"{type(exc).__name__}: {str(exc)[:300]}"
    finally:
        adapter_logger.removeHandler(counter)
        adapter_logger.setLevel(previous_level)
        result.latency_seconds = round(time.perf_counter() - started, 2)
        result.prompt_tokens = counter.prompt_tokens
        result.completion_tokens = counter.completion_tokens
        result.llm_calls = counter.calls
    return result


def _print_summary(results: list[TopicResult]) -> None:
    print()
    print(f"{'topic':28} {'pass':5} {'lessons':8} {'skills':7} {'edges':6} "
          f"{'lat(s)':8} {'tok(in/out)':14} {'calls':6}")
    print("-" * 92)
    for r in results:
        print(
            f"{r.id:28} {str(r.passed):5} "
            f"{f'{r.lessons_ok}/{r.lessons_total}':8} {r.skills:<7} {r.edges:<6} "
            f"{r.latency_seconds:<8} {f'{r.prompt_tokens}/{r.completion_tokens}':14} {r.llm_calls:<6}"
        )
        if r.error:
            print(f"    error: {r.error}")
        for failure in r.lesson_failures:
            print(f"    lesson failure: {failure}")

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    calls = sum(r.llm_calls for r in results)
    tokens_in = sum(r.prompt_tokens for r in results)
    tokens_out = sum(r.completion_tokens for r in results)
    print("-" * 92)
    print(f"Tổng: {passed}/{total} topic đạt; {calls} request; "
          f"{tokens_in} prompt / {tokens_out} completion tokens")
    print("Lưu ý: đây là đánh giá *deterministic* (schema/curriculum/lint). "
          "Chất lượng sư phạm/nội dung KHÔNG được kết luận từ script này.")


async def main_async(topic_count: int, output: pathlib.Path | None) -> int:
    settings = get_settings()
    if (settings.llm_provider or "").strip().lower() == "mock":
        print("BLOCKED: LLM_PROVIDER=mock — đây là eval provider thật, cần cấu hình provider.")
        return 2
    try:
        provider = get_provider()
    except ProviderConfigError as exc:
        print(f"BLOCKED: {exc}")
        return 2

    print(f"Provider={provider.name} model={settings.llm_model} prompt={PROMPT_VERSION}")
    results: list[TopicResult] = []
    for spec in TOPICS[:topic_count]:
        print(f"→ {spec['id']} ({spec['topic']})")
        result = await evaluate_topic(provider, spec)
        print(f"   pass={result.passed} lessons={result.lessons_ok}/{result.lessons_total} "
              f"{result.latency_seconds}s tokens={result.prompt_tokens}/{result.completion_tokens}")
        results.append(result)

    _print_summary(results)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    target = output or REPORT_DIR / f"p21_real_{time.strftime('%Y%m%d_%H%M%S')}.json"
    report = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "provider": provider.name,
        "model": settings.llm_model,
        "promptVersion": PROMPT_VERSION,
        "topics": [r.to_dict() for r in results],
        "totals": {
            "topics": len(results),
            "passed": sum(1 for r in results if r.passed),
            "llmCalls": sum(r.llm_calls for r in results),
            "promptTokens": sum(r.prompt_tokens for r in results),
            "completionTokens": sum(r.completion_tokens for r in results),
        },
    }
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {target}")
    return 0 if all(r.passed for r in results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="P2.1 real provider evaluation")
    parser.add_argument("--topics", type=int, default=1, help="số topic chạy thật (1..%d)" % len(TOPICS))
    parser.add_argument("--output", type=pathlib.Path, default=None)
    parser.add_argument("--yes", action="store_true", help="xác nhận đồng ý phát sinh chi phí")
    args = parser.parse_args()
    if not args.yes:
        print("Từ chối chạy: cần --yes để xác nhận phát sinh chi phí provider thật.")
        return 2
    count = max(1, min(args.topics, len(TOPICS)))
    for key in ("LLM_PROVIDER", "LLM_MODEL"):
        if not os.environ.get(key):
            print(f"Cảnh báo: biến {key} không có trong env, dùng giá trị từ .env")
    return asyncio.run(main_async(count, args.output))


if __name__ == "__main__":
    sys.exit(main())
