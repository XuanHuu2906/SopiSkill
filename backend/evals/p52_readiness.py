"""P5.2a — Readiness assessment cho DKT/LSTM và contextual bandit (CHỈ ĐỌC).

Trả lời bằng số, không bằng cảm nhận: còn thiếu bao nhiêu dữ liệu để (a) huấn luyện
một mô hình chuỗi như DKT/LSTM, (b) đánh giá off-policy một contextual bandit.

Không tạo bảng, không ghi, không gọi network, không huấn luyện gì. Chạy được trên
SQLite (test) lẫn PostgreSQL (thật).

    cd backend
    python -m evals.p52_readiness --database-url postgresql+asyncpg://ailp:***@127.0.0.1:5433/ailp
    python -m evals.p52_readiness --json --save

Vì sao bandit bị chặn kể cả khi có exposure: policy hiện **deterministic** nên
`propensity = 1.0` cho mọi arm ⇒ thiếu overlap ⇒ OPE không hợp lệ về mặt thống kê.
Report luôn ghi `opeSupported = false`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from evals import mastery_dataset as md

REPORT_DIR = pathlib.Path(__file__).parent / "reports"
EVAL_VERSION = "p5.2-readiness-v1"

DEFAULT_THRESHOLDS = {
    # DKT/LSTM: mô hình chuỗi cần nhiều user có lịch sử dài.
    "dkt_users_ge10": 500,
    "dkt_sequences_ge5": 200,
    "dkt_courses_ge2_users": 50,
    # Contextual bandit: cần nhiều exposure, nhiều policy, nhiều arm, và propensity
    # phải có spread (hiện 1.0 ⇒ spread 0 ⇒ không bao giờ đạt).
    "bandit_exposures": 5000,
    "bandit_policies": 2,
    "bandit_arms": 3,
    "bandit_propensity_spread": 0.1,
}

try:  # Windows console mặc định cp1258/cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except (AttributeError, OSError):  # pragma: no cover
    pass


async def _scalar(conn, sql: str) -> int:
    value = (await conn.execute(text(sql))).scalar()
    return int(value or 0)


async def collect_metrics(engine) -> dict:
    tables = await md.detect_tables(engine)
    metrics: dict = {
        "tables": sorted(tables),
        "attempts": 0,
        "usersWithAttempts": 0,
        "maxAttemptsPerUser": 0,
        "usersGe5": 0,
        "usersGe10": 0,
        "usersGe20": 0,
        "sequencesGe5": 0,
        "coursesWithGe2Users": 0,
        "exposureRows": 0,
        "distinctPolicies": 0,
        "distinctArms": 0,
        "propensityMin": None,
        "propensityMax": None,
    }

    if {"lesson_attempts", "lessons", "units", "courses"} <= tables:
        async with engine.connect() as conn:
            metrics["attempts"] = await _scalar(
                conn, "SELECT COUNT(*) FROM lesson_attempts"
            )
            metrics["usersWithAttempts"] = await _scalar(
                conn, "SELECT COUNT(DISTINCT user_id) FROM lesson_attempts"
            )
            metrics["maxAttemptsPerUser"] = await _scalar(
                conn,
                "SELECT COALESCE(MAX(n), 0) FROM "
                "(SELECT COUNT(*) AS n FROM lesson_attempts GROUP BY user_id) t",
            )
            for threshold, key in ((5, "usersGe5"), (10, "usersGe10"), (20, "usersGe20")):
                metrics[key] = await _scalar(
                    conn,
                    "SELECT COUNT(*) FROM "
                    f"(SELECT user_id FROM lesson_attempts GROUP BY user_id "
                    f"HAVING COUNT(*) >= {int(threshold)}) t",
                )
            # `lesson_attempts` không có course_id ⇒ phải đi qua lessons/units.
            metrics["coursesWithGe2Users"] = await _scalar(
                conn,
                "SELECT COUNT(*) FROM ("
                "  SELECT c.id FROM courses c"
                "  JOIN units u ON u.course_id = c.id"
                "  JOIN lessons l ON l.unit_id = u.id"
                "  JOIN lesson_attempts a ON a.lesson_id = l.id"
                "  GROUP BY c.id HAVING COUNT(DISTINCT a.user_id) >= 2"
                ") t",
            )

    # Tái dùng extractor P5.1 (đã xử lý fallback schema 0012 + contentVersion).
    try:
        sequences, _report = await md.load_sequences(engine, granularity="skill")
        metrics["sequencesGe5"] = sum(
            1 for seq in sequences if len(seq.events) >= 5
        )
    except Exception:  # pragma: no cover - thiếu bảng lesson_attempts
        metrics["sequencesGe5"] = 0

    if "recommendation_events" in tables:
        async with engine.connect() as conn:
            metrics["exposureRows"] = await _scalar(
                conn, "SELECT COUNT(*) FROM recommendation_events"
            )
            metrics["distinctPolicies"] = await _scalar(
                conn,
                "SELECT COUNT(*) FROM ("
                "  SELECT DISTINCT policy_version FROM recommendation_events"
                ") t",
            )
            # Không dùng COUNT(DISTINCT a, b): SQLite không hỗ trợ nhiều cột.
            metrics["distinctArms"] = await _scalar(
                conn,
                "SELECT COUNT(*) FROM ("
                "  SELECT DISTINCT arm_kind, arm_id FROM recommendation_events"
                ") t",
            )
            row = (
                await conn.execute(
                    text(
                        "SELECT MIN(propensity), MAX(propensity) "
                        "FROM recommendation_events"
                    )
                )
            ).first()
            if row is not None:
                metrics["propensityMin"] = None if row[0] is None else float(row[0])
                metrics["propensityMax"] = None if row[1] is None else float(row[1])
    return metrics


def decide(metrics: dict, thresholds: dict) -> dict:
    """Quyết định verdict từng hạng mục. Trung thực khi thiếu dữ liệu."""
    dkt_reasons: list[str] = []
    if metrics["usersGe10"] < thresholds["dkt_users_ge10"]:
        dkt_reasons.append(
            f"usersGe10={metrics['usersGe10']} < {thresholds['dkt_users_ge10']}"
        )
    if metrics["sequencesGe5"] < thresholds["dkt_sequences_ge5"]:
        dkt_reasons.append(
            f"sequencesGe5={metrics['sequencesGe5']} < {thresholds['dkt_sequences_ge5']}"
        )
    if metrics["coursesWithGe2Users"] < thresholds["dkt_courses_ge2_users"]:
        dkt_reasons.append(
            f"coursesWithGe2Users={metrics['coursesWithGe2Users']} "
            f"< {thresholds['dkt_courses_ge2_users']}"
        )

    bandit_reasons: list[str] = []
    if metrics["exposureRows"] < thresholds["bandit_exposures"]:
        bandit_reasons.append(
            f"exposureRows={metrics['exposureRows']} < {thresholds['bandit_exposures']}"
        )
    if metrics["distinctPolicies"] < thresholds["bandit_policies"]:
        bandit_reasons.append(
            f"distinctPolicies={metrics['distinctPolicies']} "
            f"< {thresholds['bandit_policies']}"
        )
    if metrics["distinctArms"] < thresholds["bandit_arms"]:
        bandit_reasons.append(
            f"distinctArms={metrics['distinctArms']} < {thresholds['bandit_arms']}"
        )
    spread = _propensity_spread(metrics)
    if spread is None or spread < thresholds["bandit_propensity_spread"]:
        bandit_reasons.append(
            f"propensitySpread={spread} < {thresholds['bandit_propensity_spread']} "
            "(policy deterministic ⇒ chưa thể OPE)"
        )

    return {
        "dkt": {
            "verdict": "READY" if not dkt_reasons else "BLOCKED",
            "reasons": dkt_reasons,
            "modelTrained": False,
        },
        "bandit": {
            "verdict": "READY" if not bandit_reasons else "BLOCKED",
            "reasons": bandit_reasons,
            "modelTrained": False,
            "opeSupported": False,
        },
    }


def _propensity_spread(metrics: dict) -> float | None:
    low, high = metrics.get("propensityMin"), metrics.get("propensityMax")
    if low is None or high is None:
        return None
    return round(float(high) - float(low), 6)


def _print(payload: dict) -> None:
    metrics = payload["metrics"]
    print(f"P5.2 readiness {EVAL_VERSION} — {payload['database']}")
    print(
        f"  attempts={metrics['attempts']} users={metrics['usersWithAttempts']} "
        f"maxPerUser={metrics['maxAttemptsPerUser']} "
        f"usersGe10={metrics['usersGe10']} sequencesGe5={metrics['sequencesGe5']} "
        f"coursesGe2Users={metrics['coursesWithGe2Users']}"
    )
    print(
        f"  exposures={metrics['exposureRows']} policies={metrics['distinctPolicies']} "
        f"arms={metrics['distinctArms']} propensitySpread={_propensity_spread(metrics)}"
    )
    for name in ("dkt", "bandit"):
        block = payload[name]
        print(f"  {name.upper()}: {block['verdict']}")
        for reason in block["reasons"]:
            print(f"    - {reason}")
    print(f"  opeSupported={payload['bandit']['opeSupported']}")


WORDS = {2: "hai", 3: "ba"}


async def _run(args) -> dict:
    dsn = args.database_url or _default_dsn()
    engine = create_async_engine(dsn)
    try:
        metrics = await collect_metrics(engine)
    finally:
        await engine.dispose()

    thresholds = {**DEFAULT_THRESHOLDS}
    verdicts = decide(metrics, thresholds)
    payload = {
        "evalVersion": EVAL_VERSION,
        "database": md.redact_dsn(dsn),
        "generatedAt": datetime.now(UTC).isoformat(),
        "thresholds": thresholds,
        "metrics": metrics,
        **verdicts,
    }
    _print(payload)
    return payload


def _default_dsn() -> str:
    from app.core.config import get_settings

    return str(get_settings().database_url)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Đo mức sẵn sàng cho DKT/LSTM và contextual bandit (chỉ đọc). "
            f"Ngưỡng mặc định: {DEFAULT_THRESHOLDS}"
        )
    )
    parser.add_argument("--database-url", default=None, help="DSN chỉ đọc")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--save", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = asyncio.run(_run(args))
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.save:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        path = REPORT_DIR / f"p52_readiness_{stamp}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
