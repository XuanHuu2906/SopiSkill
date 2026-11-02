"""P5.1 — Bayesian Knowledge Tracing (research-only, KHÔNG dùng ở runtime).

Vì sao tách riêng:
  - Mastery đang chạy (P5.0) là heuristic accuracy có trọng số thời gian, KHÔNG
    phải xác suất đã hiệu chuẩn. Module này chỉ để **nghiên cứu/đo lường** xem
    BKT có dự đoán tốt hơn baseline đó trên dữ liệu thật hay không.
  - Không import từ route/service/worker. Không đọc/ghi DB. Hàm thuần, test
    deterministic trên SQLite.

Mục tiêu so sánh:
  - Cả hai mô hình dự đoán **điểm mềm** `y = score_correct / score_total` ∈ [0,1]
    (đúng một phần của bài 5 câu ⇒ y = k/5), không phải nhị phân 0/1. Brier là
    `(p - y)**2`. Nhờ vậy BKT và baseline được chấm trên cùng một đại lượng.
  - `predict_correct` trả **xác suất đúng** `P(correct) = P(L)(1-slip) +
    (1-P(L))*guess`, KHÔNG trả prior P(L). Đây là con số đem so với y.

Quy ước số học:
  - Mọi xác suất clamp vào `[EPS, 1-EPS]` với `EPS = 1e-9` để tránh 0/1 tuyệt đối
    (log loss/Bayes không chia 0).
  - `observe` dùng Bayes **mềm** để giữ tính liên tục của mục tiêu:
        P(y|mastered)     = (1 - slip) * y + slip * (1 - y)
        P(y|not mastered) = guess * y + (1 - guess) * (1 - y)
    Khi y → 1/0, công thức hội tụ về Bayes nhị phân kinh điển.
  - `apply_learning` chạy **sau** mỗi quan sát: `p + (1-p)*p_learn`.

KHÔNG tuyên bố module này là "AI adaptive đã triển khai". Kết quả trên dữ liệu
thật hiện tại là `INSUFFICIENT_DATA` (xem `docs/specs/23-P51-BKT.md`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

EPS = 1e-9


@dataclass(frozen=True)
class BktParams:
    """4 tham số BKT kinh điển. Giá trị mặc định là baseline phổ biến, không fit."""

    p_init: float = 0.3
    p_learn: float = 0.2
    p_guess: float = 0.2
    p_slip: float = 0.1


def _clamp(value: float) -> float:
    if value < EPS:
        return EPS
    if value > 1 - EPS:
        return 1 - EPS
    return value


def validate(params: BktParams) -> None:
    """Kiểm tra tham số hợp lệ về mặt xác suất; raise `ValueError` nếu sai."""
    for name in ("p_init", "p_learn", "p_guess", "p_slip"):
        value = float(getattr(params, name))
        if not (0.0 < value < 1.0):
            raise ValueError(f"{name} phải nằm trong (0, 1), nhận {value}")
    if params.p_guess + params.p_slip >= 1.0:
        raise ValueError(
            "p_guess + p_slip phải < 1 để mô hình còn nhận dạng được, "
            f"nhận {params.p_guess + params.p_slip}"
        )


def _likelihood_mastered(y: float, params: BktParams) -> float:
    return (1.0 - params.p_slip) * y + params.p_slip * (1.0 - y)


def _likelihood_not(y: float, params: BktParams) -> float:
    return params.p_guess * y + (1.0 - params.p_guess) * (1.0 - y)


def observe(prior: float, y: float, params: BktParams) -> float:
    """Posterior P(L) sau một quan sát mềm `y` (0..1)."""
    prior = _clamp(float(prior))
    y = _clamp(float(y))
    num = _likelihood_mastered(y, params) * prior
    den = num + _likelihood_not(y, params) * (1.0 - prior)
    if den <= 0:  # pragma: no cover - chỉ xảy ra với tham số thoái hoá
        return prior
    return _clamp(num / den)


def apply_learning(posterior: float, params: BktParams) -> float:
    """Chuyển posterior thành prior của lần kế tiếp."""
    posterior = _clamp(float(posterior))
    return _clamp(posterior + (1.0 - posterior) * params.p_learn)


def predict_correct(priors: Sequence[float], params: BktParams) -> list[float]:
    """P(correct) cho từng prior P(L)."""
    return [
        _clamp(_clamp(float(p)) * (1.0 - params.p_slip) + (1.0 - _clamp(float(p))) * params.p_guess)
        for p in priors
    ]


def predict_sequence(observations: Sequence[float], params: BktParams) -> list[float]:
    """Dự đoán P(correct) TRƯỚC mỗi quan sát, chỉ dùng quá khứ.

    `predict_sequence(obs)[i]` không được phụ thuộc vào `observations[i:]`; trả
    cùng độ dài với `observations`.
    """
    prior = _clamp(params.p_init)
    out: list[float] = []
    for raw in observations:
        out.append(predict_correct([prior], params)[0])
        posterior = observe(prior, raw, params)
        prior = apply_learning(posterior, params)
    return out


def brier(preds: Sequence[float], targets: Sequence[float]) -> float:
    if len(preds) != len(targets):
        raise ValueError("preds và targets phải cùng độ dài")
    if not preds:
        raise ValueError("brier cần ít nhất một phần tử")
    total = 0.0
    for p, t in zip(preds, targets):
        total += (float(p) - float(t)) ** 2
    return total / len(preds)


def fit_grid(
    train: Sequence[Sequence[float]],
    grid: Sequence[BktParams],
) -> tuple[BktParams, float]:
    """Chọn tham số tốt nhất trên train theo Brier. Hòa ⇒ giữ phần tử sớm hơn."""
    if not grid:
        raise ValueError("grid rỗng")
    if not any(len(seq) > 0 for seq in train):
        raise ValueError("train không có quan sát nào")

    best = grid[0]
    best_score = float("inf")
    # Lưới được duyệt đúng thứ tự đầu vào để tái lập; hòa giữ phần tử sớm.
    for params in grid:
        validate(params)
        ps: list[float] = []
        ts: list[float] = []
        for seq in train:
            seq_list = [float(x) for x in seq]
            if not seq_list:
                continue
            ps.extend(predict_sequence(seq_list, params))
            ts.extend(seq_list)
        score = brier(ps, ts)
        if score < best_score:
            best_score = score
            best = params
    return best, best_score
