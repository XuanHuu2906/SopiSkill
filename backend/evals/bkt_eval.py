"""P5.1 — BKT evaluation harness (offline, read-only, không tốn phí).

Hai chế độ:
  - `--dataset real`      : đọc database thật (chỉ SELECT). Dữ liệu chưa đủ thì in
                            `INSUFFICIENT_DATA` kèm lý do định lượng và exit 0 —
                            KHÔNG bao giờ in PASS giả.
  - `--dataset simulated` : sinh chuỗi từ BKT với tham số đã biết, seed cố định.
                            Dùng để chứng minh thuật toán/split/metric hoạt động;
                            report ghi `dataSource="simulated"`, KHÔNG suy rộng.

Mục tiêu so sánh (xem `app/services/bkt.py`): cả BKT và baseline dự đoán **điểm mềm**
`y = score_correct/score_total`; Brier = `(p - y)^2`.

Baseline (as-of, KHÔNG leakage): tại mỗi event dùng trung bình có trọng số thời gian
của các event **trước đó của cùng chuỗi**; chưa có lịch sử ⇒ dùng trung bình `y` của
train. Tuyệt đối không gọi `compute_mastery(now=...)` (sẽ nhìn thấy tương lai).

Ví dụ:
    cd backend
    python -m evals.bkt_eval --dataset real \
        --database-url postgresql+asyncpg://ailp:***@127.0.0.1:5433/ailp
    python -m evals.bkt_eval --dataset simulated --seed 20261102 --save
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import pathlib
import random
import subprocess
import sys
import urllib.parse
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services import bkt
from evals import mastery_dataset as md

REPORT_DIR = pathlib.Path(__file__).parent / "reports"
EVAL_VERSION = "p5.1-bkt-v1"
CUTOFF_THRESHOLD = 0.8
DEFAULT_GRID = [bkt.BktParams(p_learn=value) for value in (0.02, 0.05, 0.1, 0.2, 0.35)]

try:  # Windows console mặc định cp1258/cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except (AttributeError, OSError):  # pragma: no cover
    pass


def _clamp(value: float, low: float = 1e-9, high: float = 1 - 1e-9) -> float:
    return max(low, min(high, value))


def _event_y(event: Any) -> float:
    """Event có thể là `(timestamp, y)` hoặc chỉ `y`."""
    if isinstance(event, (int, float)):
        return float(event)
    return float(event[-1])


def _event_ts(event: Any) -> datetime | None:
    if isinstance(event, (int, float)):
        return None
    first = event[0]
    if isinstance(first, datetime):
        return first if first.tzinfo else first.replace(tzinfo=UTC)
    return None


def _as_float_sequences(sequences: list[list[Any]]) -> list[list[float]]:
    return [[_event_y(event) for event in seq] for seq in sequences]


def split_by_user(keys: list[str], ratio: float = 0.7) -> tuple[set[str], set[str]]:
    """Chia theo tên user *trước* dấu `:` để không user nào xuất hiện ở 2 phía.

    Trả về **tập key gốc** (không phải tên user) để caller lọc chuỗi trực tiếp;
    phép chia vẫn tính theo user nên không thể có leakage.
    """
    users = sorted({key.split(":", 1)[0] for key in keys})
    if not users:
        return set(), set()
    cut = int(round(len(users) * ratio))
    # Đảm bảo cả hai phía có ít nhất 1 user khi có ≥2 user.
    if len(users) >= 2:
        cut = min(max(cut, 1), len(users) - 1)
    train_users, test_users = set(users[:cut]), set(users[cut:])
    return (
        {key for key in keys if key.split(":", 1)[0] in train_users},
        {key for key in keys if key.split(":", 1)[0] in test_users},
    )


def split_by_time(
    rows: list[tuple[str, datetime]], cutoff: datetime
) -> tuple[set[str], set[str]]:
    train = {key for key, ts in rows if ts < cutoff}
    test = {key for key, ts in rows if ts >= cutoff}
    return train, test


def _brier(preds: list[float], targets: list[float]) -> float | None:
    if not preds:
        return None
    return sum((p - t) ** 2 for p, t in zip(preds, targets)) / len(preds)


def _log_loss(preds: list[float], targets: list[float]) -> float | None:
    if not preds:
        return None
    total = 0.0
    for p, t in zip(preds, targets):
        p = _clamp(p)
        total += -(t * math.log(p) + (1 - t) * math.log(1 - p))
    return total / len(preds)


def _auc(preds: list[float], binary: list[int]) -> float | None:
    """AUC rank-based; trả None nếu chỉ có một lớp nhãn."""
    positives = [p for p, label in zip(preds, binary) if label == 1]
    negatives = [p for p, label in zip(preds, binary) if label == 0]
    if not positives or not negatives:
        return None
    # Đếm cặp (pos, neg) có pred_pos > pred_neg; hòa tính 0.5.
    wins = 0.0
    for pos in positives:
        for neg in negatives:
            if pos > neg:
                wins += 1.0
            elif pos == neg:
                wins += 0.5
    return wins / (len(positives) * len(negatives))


def _ece(preds: list[float], targets: list[float], bins: int = 10) -> float | None:
    if not preds:
        return None
    buckets: list[list[tuple[float, float]]] = [[] for _ in range(bins)]
    for p, t in zip(preds, targets):
        index = min(bins - 1, max(0, int(_clamp(p) * bins)))
        buckets[index].append((p, t))
    total = len(preds)
    score = 0.0
    for bucket in buckets:
        if not bucket:
            continue
        avg_p = sum(p for p, _ in bucket) / len(bucket)
        avg_t = sum(t for _, t in bucket) / len(bucket)
        score += (len(bucket) / total) * abs(avg_p - avg_t)
    return score


def _baseline_predictions(
    train: list[list[float]], test: list[list[Any]]
) -> list[float]:
    """Baseline as-of: trung bình có trọng số thời gian của event TRƯỚC đó."""
    train_flat = [y for seq in train for y in seq]
    fallback = sum(train_flat) / len(train_flat) if train_flat else 0.5

    preds: list[float] = []
    for raw_seq in test:
        history: list[tuple[datetime | None, float]] = []
        for event in raw_seq:
            y = _event_y(event)
            ts = _event_ts(event)
            if not history:
                preds.append(fallback)
            else:
                if ts is None:
                    # Không có timestamp ⇒ trọng số đều (vẫn chỉ dùng quá khứ).
                    weights = [1.0 for _ in history]
                else:
                    weights = []
                    for hist_ts, _ in history:
                        if hist_ts is None:
                            weights.append(1.0)
                        else:
                            age_days = max(0.0, (ts - hist_ts).total_seconds() / 86400.0)
                            weights.append(0.5 ** (age_days / 30.0))
                total_weight = sum(weights)
                if total_weight <= 0:
                    preds.append(fallback)
                else:
                    preds.append(
                        sum(w * h for w, (_, h) in zip(weights, history)) / total_weight
                    )
            history.append((ts, y))
    return preds


def evaluate(
    train: list[list[Any]],
    test: list[list[Any]],
    *,
    train_users: list[str] | None = None,
    test_users: list[str] | None = None,
) -> dict:
    """So BKT (fit trên train) với baseline as-of, đo trên test."""
    train_float = _as_float_sequences(train)
    test_float = _as_float_sequences(test)

    n_test = sum(len(seq) for seq in test_float)
    n_train = sum(len(seq) for seq in train_float)

    train_users = train_users or []
    test_users = test_users or []
    leakage = len(set(train_users) & set(test_users))

    result: dict[str, Any] = {
        "nTrain": n_train,
        "nTest": n_test,
        "nEvents": n_train + n_test,
        "nSequencesTrain": len(train_float),
        "nSequencesTest": len(test_float),
        "leakage": leakage,
        "brierBkt": None,
        "brierBaseline": None,
        "logLossBkt": None,
        "logLossBaseline": None,
        "aucBkt": None,
        "aucBaseline": None,
        "eceBkt": None,
        "eceBaseline": None,
        "driftBrier": None,
        "params": None,
        "trainBrier": None,
        "grid": [p.p_learn for p in DEFAULT_GRID],
    }
    if not n_test:
        return result

    try:
        params, train_brier = bkt.fit_grid(
            [seq for seq in train_float if seq], DEFAULT_GRID
        )
    except ValueError:
        params, train_brier = bkt.BktParams(), None
    result["params"] = {
        "pInit": params.p_init,
        "pLearn": params.p_learn,
        "pGuess": params.p_guess,
        "pSlip": params.p_slip,
    }
    result["trainBrier"] = train_brier

    bkt_preds = [
        p for seq in test_float if seq for p in bkt.predict_sequence(seq, params)
    ]
    base_preds = _baseline_predictions(train_float, test)
    targets = [y for seq in test_float for y in seq]
    binary = [1 if y >= CUTOFF_THRESHOLD else 0 for y in targets]

    result["brierBkt"] = _brier(bkt_preds, targets)
    result["brierBaseline"] = _brier(base_preds, targets)
    result["logLossBkt"] = _log_loss(bkt_preds, targets)
    result["logLossBaseline"] = _log_loss(base_preds, targets)
    result["aucBkt"] = _auc(bkt_preds, binary)
    result["aucBaseline"] = _auc(base_preds, binary)
    result["eceBkt"] = _ece(bkt_preds, targets)
    result["eceBaseline"] = _ece(base_preds, targets)

    # Drift: Brier trên nửa sau trừ nửa đầu của test (theo thứ tự chuỗi).
    half = len(targets) // 2
    if half > 0:
        early = _brier(bkt_preds[:half], targets[:half])
        late = _brier(bkt_preds[half:], targets[half:])
        if early is not None and late is not None:
            result["driftBrier"] = late - early
    return result


def simulate(
    seed: int,
    users: int,
    per_user: int,
    params: bkt.BktParams,
    *,
    force_correct: bool = False,
) -> list[md.Sequence]:
    """Sinh chuỗi từ BKT với tham số đã biết (nhãn rõ là mô phỏng).

    Mỗi "bài" tương ứng một quiz 5 câu; `y = số câu đúng / 5` để mục tiêu mềm giống
    dữ liệu thật. Trạng thái ẩn bắt đầu từ `p_init`; sau mỗi bài cập nhật bằng
    chính công thức `observe` + `apply_learning` của module.
    """
    bkt.validate(params)
    rng = random.Random(seed)
    anchor = datetime(2026, 1, 1, tzinfo=UTC)
    sequences: list[md.Sequence] = []

    for user in range(users):
        latent = params.p_init
        events: list[tuple[datetime, float]] = []
        for step in range(per_user):
            p_correct = bkt.predict_correct([latent], params)[0]
            if force_correct:
                y = 1.0
            else:
                correct = sum(
                    1 for _ in range(5) if rng.random() < p_correct
                )
                y = correct / 5.0
            ts = anchor + timedelta(hours=user * per_user + step)
            events.append((ts, y))
            posterior = bkt.observe(latent, y, params)
            latent = bkt.apply_learning(posterior, params)
        sequences.append(md.Sequence(user_id=f"sim-u{user}", key=f"sim-u{user}", events=events))
    return sequences


def decide_gate(results: dict, thresholds: dict) -> dict:
    """Quyết định gate theo ngưỡng đã công bố; trung thực khi thiếu dữ liệu."""
    min_sequences = int(thresholds.get("min_sequences", 30))
    min_events = int(thresholds.get("min_events", 300))
    min_gain = float(thresholds.get("min_relative_brier_gain", 0.02))
    max_ece = float(thresholds.get("max_ece", 0.10))
    min_auc = float(thresholds.get("min_auc", 0.60))
    max_drift = float(thresholds.get("max_drift", 0.05))

    n_test_sequences = int(results.get("nSequencesTest", 0) or 0)
    n_events = int(results.get("nEvents", 0) or 0)
    required_test = max(10, min_sequences // 3)

    reasons: list[str] = []
    if int(results.get("nSequencesTrain", 0) or 0) < required_test:
        reasons.append(
            f"train cần ≥{required_test} chuỗi, chỉ có "
            f"{int(results.get('nSequencesTrain', 0) or 0)}"
        )
    if n_test_sequences < required_test:
        reasons.append(f"test cần ≥{required_test} chuỗi, chỉ có {n_test_sequences}")
    if n_events < min_events:
        reasons.append(f"min_events={min_events}: chỉ có {n_events} event")
    if reasons:
        return {"status": "insufficient_data", "gate": "NOT_MET", "reasons": reasons}

    leakage = int(results.get("leakage", 0) or 0)
    if leakage:
        reasons.append(f"leakage={leakage}: user xuất hiện ở cả train và test")

    brier_bkt = results.get("brierBkt")
    brier_base = results.get("brierBaseline")
    if brier_bkt is None or brier_base is None:
        reasons.append("thiếu Brier (không có dự đoán test)")
    elif brier_base <= 0:
        if brier_bkt > 0:
            reasons.append("baseline Brier=0 nhưng BKT > 0")
    else:
        gain = (brier_base - brier_bkt) / brier_base
        if gain < min_gain:
            reasons.append(
                f"brier gain {gain:.4f} < {min_gain} "
                f"(bkt={brier_bkt:.4f}, baseline={brier_base:.4f})"
            )

    ece = results.get("eceBkt")
    if ece is None or ece > max_ece:
        reasons.append(f"eceBkt={ece} vượt max_ece={max_ece}")

    auc = results.get("aucBkt")
    if auc is None or auc < min_auc:
        reasons.append(f"aucBkt={auc} dưới min_auc={min_auc}")

    drift = results.get("driftBrier")
    if drift is None or abs(drift) > max_drift:
        reasons.append(f"driftBrier={drift} vượt max_drift={max_drift}")

    return {
        "status": "evaluated",
        "gate": "PASS" if not reasons else "NOT_MET",
        "reasons": reasons,
    }


def _git_head() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        return None
    return out.stdout.strip() or None


def _print_report(payload: dict) -> None:
    print(f"BKT eval {EVAL_VERSION} — dataSource={payload.get('dataSource')}")
    if payload.get("database"):
        print(f"  database: {payload['database']}")
    dataset = payload.get("dataset") or {}
    if dataset:
        print(
            f"  users={dataset.get('users')} sequences={dataset.get('sequences')} "
            f"rawAttempts={dataset.get('rawAttempts')} "
            f"versionedAttempts={dataset.get('versionedAttempts')} "
            f"skillGranularity={dataset.get('skillGranularity')}"
        )
        print(f"  lengthHistogram={dataset.get('lengthHistogram')}")
    results = payload.get("results") or {}
    if results:
        print(
            f"  brier bkt={results.get('brierBkt')} baseline={results.get('brierBaseline')} "
            f"logloss bkt={results.get('logLossBkt')} "
            f"auc bkt={results.get('aucBkt')} ece bkt={results.get('eceBkt')} "
            f"drift={results.get('driftBrier')} leakage={results.get('leakage')}"
        )
    gate = payload.get("gate") or {}
    print(f"  PHASE GATE: {gate.get('gate')} status={gate.get('status')}")
    for reason in gate.get("reasons", []):
        print(f"    - {reason}")


def _save(payload: dict) -> pathlib.Path | None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    path = REPORT_DIR / f"bkt_{payload.get('dataSource','unknown')}_{stamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


async def _run_real(args) -> dict:
    from sqlalchemy.ext.asyncio import create_async_engine

    dsn = args.database_url or _default_database_url()
    engine = create_async_engine(dsn)
    try:
        sequences, report = await md.load_sequences(
            engine, granularity=args.granularity, min_sequence=args.min_sequence
        )
    finally:
        await engine.dispose()

    payload: dict[str, Any] = {
        "evalVersion": EVAL_VERSION,
        "dataSource": "real",
        "database": md.redact_dsn(dsn),
        "gitHead": _git_head(),
        "seed": args.seed,
        "thresholds": _thresholds(args),
        "dataset": report.as_dict(),
    }
    summary = md.summarize(report, payload["thresholds"])
    if not summary["enough"]:
        payload["status"] = "insufficient_data"
        payload["results"] = {}
        payload["gate"] = {
            "status": "insufficient_data",
            "gate": "NOT_MET",
            "reasons": summary["reasons"],
        }
        _print_report(payload)
        print("INSUFFICIENT_DATA")
        return payload

    keys = [f"{seq.user_id}:{seq.key}" for seq in sequences]
    train_keys, test_keys = split_by_user(keys, ratio=0.7)
    train = [seq.events for seq in sequences if f"{seq.user_id}:{seq.key}" in train_keys]
    test = [seq.events for seq in sequences if f"{seq.user_id}:{seq.key}" in test_keys]
    train_users = [seq.user_id for seq in sequences if f"{seq.user_id}:{seq.key}" in train_keys]
    test_users = [seq.user_id for seq in sequences if f"{seq.user_id}:{seq.key}" in test_keys]

    results = evaluate(train, test, train_users=train_users, test_users=test_users)
    payload["status"] = "evaluated"
    payload["results"] = results
    payload["gate"] = decide_gate(results, payload["thresholds"])
    _print_report(payload)
    return payload


def _run_simulated(args) -> dict:
    params = bkt.BktParams(
        p_init=args.p_init,
        p_learn=args.p_learn,
        p_guess=args.p_guess,
        p_slip=args.p_slip,
    )
    sequences = simulate(
        seed=args.seed,
        users=args.sim_users,
        per_user=args.sim_per_user,
        params=params,
        force_correct=args.force_correct,
    )
    keys = [f"{seq.user_id}:{seq.key}" for seq in sequences]
    train_keys, test_keys = split_by_user(keys, ratio=0.7)
    train = [seq.events for seq in sequences if f"{seq.user_id}:{seq.key}" in train_keys]
    test = [seq.events for seq in sequences if f"{seq.user_id}:{seq.key}" in test_keys]
    train_users = [seq.user_id for seq in sequences if f"{seq.user_id}:{seq.key}" in train_keys]
    test_users = [seq.user_id for seq in sequences if f"{seq.user_id}:{seq.key}" in test_keys]

    results = evaluate(train, test, train_users=train_users, test_users=test_users)
    report = md.DatasetReport(
        database="<simulated>",
        skill_granularity=True,
        users=args.sim_users,
        sequences=len(sequences),
        raw_attempts=sum(len(seq.events) for seq in sequences),
        versioned_attempts=sum(len(seq.events) for seq in sequences),
        length_histogram={str(args.sim_per_user): len(sequences)},
        sequences_ge={
            str(n): sum(1 for seq in sequences if len(seq.events) >= n)
            for n in md.LENGTH_THRESHOLDS
        },
        min_sequence=args.min_sequence,
    )
    payload: dict[str, Any] = {
        "evalVersion": EVAL_VERSION,
        "dataSource": "simulated",
        "database": "<simulated>",
        "gitHead": _git_head(),
        "seed": args.seed,
        "simulationParams": {
            "pInit": params.p_init,
            "pLearn": params.p_learn,
            "pGuess": params.p_guess,
            "pSlip": params.p_slip,
            "users": args.sim_users,
            "perUser": args.sim_per_user,
            "forceCorrect": args.force_correct,
        },
        "thresholds": _thresholds(args),
        "dataset": report.as_dict(),
        "status": "evaluated",
        "results": results,
        "gate": decide_gate(results, _thresholds(args)),
    }
    _print_report(payload)
    return payload


def _thresholds(args) -> dict:
    return {
        "min_sequences": args.min_sequences,
        "min_events": args.min_events,
        "min_relative_brier_gain": args.min_relative_brier_gain,
        "max_ece": args.max_ece,
        "min_auc": args.min_auc,
        "max_drift": args.max_drift,
    }


def _default_database_url() -> str:
    from app.core.config import get_settings

    return str(get_settings().database_url)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="P5.1 BKT offline evaluation")
    parser.add_argument("--dataset", choices=["real", "simulated"], default="real")
    parser.add_argument("--database-url", default=None, help="DSN chỉ đọc (mặc định DATABASE_URL)")
    parser.add_argument("--granularity", choices=["skill", "lesson"], default="skill")
    parser.add_argument("--min-sequence", type=int, default=5)
    parser.add_argument("--min-sequences", type=int, default=30)
    parser.add_argument("--min-events", type=int, default=300)
    parser.add_argument("--min-relative-brier-gain", type=float, default=0.02)
    parser.add_argument("--max-ece", type=float, default=0.10)
    parser.add_argument("--min-auc", type=float, default=0.60)
    parser.add_argument("--max-drift", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=20261102)
    parser.add_argument("--sim-users", type=int, default=40)
    parser.add_argument("--sim-per-user", type=int, default=20)
    parser.add_argument("--p-init", type=float, default=0.3)
    parser.add_argument("--p-learn", type=float, default=0.2)
    parser.add_argument("--p-guess", type=float, default=0.2)
    parser.add_argument("--p-slip", type=float, default=0.1)
    parser.add_argument("--force-correct", action="store_true")
    parser.add_argument("--json", action="store_true", help="in JSON đầy đủ")
    parser.add_argument("--save", action="store_true", help="ghi report vào evals/reports/")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = (
        asyncio.run(_run_real(args))
        if args.dataset == "real"
        else _run_simulated(args)
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.save:
        path = _save(payload)
        if path is not None:
            print(f"report: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
