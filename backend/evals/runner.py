"""P2.2 eval runner (offline mock hoặc real provider có duyệt ngân sách).

Ví dụ:

    cd backend
    # Offline, không tốn tiền (mock provider)
    python -m evals.runner --provider mock --all

    # Real provider (cần --yes + LLM_API_KEY/BASE_URL/MODEL)
    python -m evals.runner --all --judge --yes

    # So sánh 2 report
    python -m evals.runner --compare evals/reports/a.json evals/reports/b.json

Report JSON ghi vào `backend/evals/reports/` (gitignored) và in bảng tóm tắt.
Không log prompt/answer; chỉ metadata topic/token/cost.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
import time

from app.core.config import get_settings
from app.providers import ProviderConfigError, get_provider
from app.providers.openai_compatible_provider import PROMPT_VERSION
from app.providers.usage import parse_pricing
from evals.dataset import dataset_summary, get_cases
from evals.pipeline import EVAL_VERSION, CaseResult, run_case, summary
from evals.regression import compare_reports
from evals.rubric import THRESHOLDS

REPORT_DIR = pathlib.Path(__file__).parent / "reports"

try:  # Windows console mặc định cp1258/cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except (AttributeError, OSError):  # pragma: no cover
    pass


def _print_case(result: CaseResult) -> None:
    print(
        f"   {'PASS' if result.passed else 'FAIL'} lessons={result.lessons_ok}/"
        f"{result.lessons_total} {result.latency_seconds}s "
        f"tokens={result.usage.get('promptTokens', 0)}/{result.usage.get('completionTokens', 0)} "
        f"cost={result.usage.get('costEstimateUsd')}"
    )
    if result.error:
        print(f"    error: {result.error}")
    for failure in result.lesson_failures[:3]:
        print(f"    lesson failure: {failure}")
    for criterion in result.rubric.get("criteria", []):
        if not criterion.get("passed"):
            print(
                f"    rubric[{criterion.get('severity')}] {criterion.get('id')}: "
                f"{criterion.get('detail')}"
            )
    if result.judge:
        print(
            f"    judge: status={result.judge.get('status')} "
            f"avg={result.judge.get('averageScore')} "
            f"model={result.judge.get('judgeModel')}"
        )


async def _run(args) -> int:
    settings = get_settings()
    provider_name = (args.provider or settings.llm_provider or "mock").strip().lower()
    if provider_name != "mock" and not args.yes:
        print("Từ chối: provider thật phát sinh chi phí, cần --yes.")
        return 2

    # Cho phép override provider mà không sửa .env (chỉ trong tiến trình này).
    if args.provider:
        settings.llm_provider = provider_name

    try:
        provider = get_provider()
    except ProviderConfigError as exc:
        print(f"BLOCKED: {exc}")
        return 2

    cases = get_cases(ids=args.topics.split(",") if args.topics else None, limit=args.limit)
    if not cases:
        print("BLOCKED: không có topic nào để chạy.")
        return 2

    dataset = dataset_summary(cases)
    if len(cases) < 10 and not args.allow_small:
        print(
            f"Từ chối: dataset {len(cases)} < 10 topic (P2.2 yêu cầu >=10). "
            "Dùng --allow-small cho smoke test."
        )
        return 2

    pricing = parse_pricing(settings.llm_pricing_json)
    print(
        f"Eval {EVAL_VERSION} provider={provider.name} model={settings.llm_model or '(n/a)'} "
        f"prompt={PROMPT_VERSION} topics={len(cases)} judge={args.judge} "
        f"costKnown={bool(pricing)}"
    )
    print(f"Dataset: {dataset}")

    results: list[CaseResult] = []
    for case in cases:
        print(f"→ {case.id} ({case.topic})")
        result = await run_case(
            provider,
            case,
            model=settings.llm_model or provider.name,
            run_judge=args.judge,
        )
        _print_case(result)
        results.append(result)

    totals = summary(results)
    print("-" * 92)
    print(
        f"Tổng: {totals['passed']}/{totals['topics']} topic pass "
        f"({totals['passRate']:.0%}); {totals['llmCalls']} request; "
        f"{totals['promptTokens']} prompt / {totals['completionTokens']} completion tokens; "
        f"cost={totals['costEstimateUsd']} (known={totals['costKnown']})"
    )
    print(
        "Lưu ý: 'pass' = rubric deterministic (schema/DAG/lint/quiz). "
        "Chất lượng sư phạm/factual cần human rubric; judge (nếu chạy) chỉ tham khảo."
    )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    target = args.output or REPORT_DIR / (
        f"p22_{provider.name}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    )
    report = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "evalVersion": EVAL_VERSION,
        "provider": provider.name,
        "model": settings.llm_model or provider.name,
        "promptVersion": PROMPT_VERSION,
        "usedRealProvider": provider.name != "mock",
        "judgeRequested": args.judge,
        "dataset": dataset,
        "thresholds": THRESHOLDS,
        "topics": [r.to_dict() for r in results],
        "totals": totals,
    }
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {target}")
    return 0 if totals["passed"] == totals["topics"] else 1


def _run_compare(paths: list[str]) -> int:
    if len(paths) != 2:
        print("--compare cần đúng 2 file report: baseline candidate")
        return 2
    baseline = json.loads(pathlib.Path(paths[0]).read_text(encoding="utf-8"))
    candidate = json.loads(pathlib.Path(paths[1]).read_text(encoding="utf-8"))
    report = compare_reports(baseline, candidate)
    data = report.to_dict()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    if not data["comparable"]:
        print(
            "Lưu ý: 2 report KHÔNG cùng provider/prompt/dataset ⇒ không kết luận regression."
        )
    return 0 if data["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="P2.2 evaluation runner")
    parser.add_argument("--provider", default=None, help="override LLM_PROVIDER (mock|openai|...)")
    parser.add_argument("--all", action="store_true", help="chạy toàn bộ dataset")
    parser.add_argument("--topics", default=None, help="danh sách id, phân tách bằng dấu phẩy")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--judge", action="store_true", help="chạy LLM-as-judge (tốn token)")
    parser.add_argument("--yes", action="store_true", help="xác nhận provider thật/chi phí")
    parser.add_argument("--allow-small", action="store_true", help="cho phép <10 topic (smoke)")
    parser.add_argument("--output", type=pathlib.Path, default=None)
    parser.add_argument("--compare", nargs="+", default=None)
    args = parser.parse_args()

    if args.compare:
        return _run_compare(args.compare)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
