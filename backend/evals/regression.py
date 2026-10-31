"""P2.2 regression evaluation — so sánh 2 report (mock↔real, prompt version↔).

Nguyên tắc: regression **chỉ fail khi thụt lùi nghiêm trọng**, không fail vì
chênh lệch nhỏ không có ý nghĩa (model không deterministic). Ngưỡng nằm trong
`REGRESSION_THRESHOLDS` và là PROPOSAL cần hiệu chỉnh.

Nếu compare chéo provider/không cùng dataset, hàm vẫn chạy nhưng đánh dấu
`comparable=False` để báo cáo không gây hiểu nhầm.
"""

from __future__ import annotations

from dataclasses import dataclass, field

REGRESSION_THRESHOLDS = {
    # Pass rate được phép giảm tối đa (tỉ lệ tuyệt đối).
    "maxPassRateDrop": 0.10,
    # Điểm judge trung bình được phép giảm tối đa (thang 0..4).
    "maxJudgeAverageDrop": 0.50,
    # Số topic fail mới được phép xuất hiện.
    "maxNewFailures": 1,
}


@dataclass
class RegressionReport:
    comparable: bool
    baseline: dict
    candidate: dict
    deltas: dict = field(default_factory=dict)
    regressions: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.regressions

    def to_dict(self) -> dict:
        return {
            "comparable": self.comparable,
            "passed": self.passed,
            "baseline": self.baseline,
            "candidate": self.candidate,
            "deltas": self.deltas,
            "regressions": self.regressions,
            "thresholds": REGRESSION_THRESHOLDS,
        }


def _ids(report: dict) -> set[str]:
    return {t.get("id") for t in report.get("topics", []) if t.get("id")}


def _failed_ids(report: dict) -> set[str]:
    return {t.get("id") for t in report.get("topics", []) if t.get("id") and not t.get("passed")}


def compare_reports(baseline: dict, candidate: dict) -> RegressionReport:
    base_totals = baseline.get("totals", {}) or {}
    cand_totals = candidate.get("totals", {}) or {}

    comparable = (
        baseline.get("provider") == candidate.get("provider")
        and baseline.get("promptVersion") == candidate.get("promptVersion")
        and _ids(baseline) == _ids(candidate)
    )

    base_rate = float(base_totals.get("passRate") or 0.0)
    cand_rate = float(cand_totals.get("passRate") or 0.0)
    rate_drop = round(base_rate - cand_rate, 4)

    base_judge = (base_totals.get("judge") or {}).get("averageScore")
    cand_judge = (cand_totals.get("judge") or {}).get("averageScore")
    judge_drop = (
        round(base_judge - cand_judge, 3)
        if isinstance(base_judge, (int, float)) and isinstance(cand_judge, (int, float))
        else None
    )

    new_failures = sorted(_failed_ids(candidate) - _failed_ids(baseline))
    fixed = sorted(_failed_ids(baseline) - _failed_ids(candidate))

    deltas = {
        "passRate": round(cand_rate - base_rate, 4),
        "passRateDrop": rate_drop,
        "judgeAverageDelta": None
        if judge_drop is None
        else round(-judge_drop, 3),
        "newFailures": new_failures,
        "fixedFailures": fixed,
    }

    regressions: list[str] = []
    if comparable:
        if rate_drop > REGRESSION_THRESHOLDS["maxPassRateDrop"]:
            regressions.append(
                f"passRate giảm {rate_drop:.2f} > {REGRESSION_THRESHOLDS['maxPassRateDrop']}"
            )
        if judge_drop is not None and judge_drop > REGRESSION_THRESHOLDS["maxJudgeAverageDrop"]:
            regressions.append(
                f"judge average giảm {judge_drop:.2f} > "
                f"{REGRESSION_THRESHOLDS['maxJudgeAverageDrop']}"
            )
        if len(new_failures) > REGRESSION_THRESHOLDS["maxNewFailures"]:
            regressions.append(
                f"{len(new_failures)} topic mới fail > {REGRESSION_THRESHOLDS['maxNewFailures']}"
            )

    return RegressionReport(
        comparable=comparable,
        baseline={
            "provider": baseline.get("provider"),
            "model": baseline.get("model"),
            "promptVersion": baseline.get("promptVersion"),
            "passRate": base_rate,
            "judgeAverage": base_judge,
        },
        candidate={
            "provider": candidate.get("provider"),
            "model": candidate.get("model"),
            "promptVersion": candidate.get("promptVersion"),
            "passRate": cand_rate,
            "judgeAverage": cand_judge,
        },
        deltas=deltas,
        regressions=regressions,
    )
