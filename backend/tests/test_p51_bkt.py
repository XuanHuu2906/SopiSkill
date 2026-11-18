"""P5.1 BKT thuần — clamp, công thức, hội tụ, chống leakage."""

import pytest

from app.services import bkt


def test_validate_rejects_out_of_range():
    with pytest.raises(ValueError):
        bkt.validate(bkt.BktParams(p_init=0.0))
    with pytest.raises(ValueError):
        bkt.validate(bkt.BktParams(p_learn=1.0))
    with pytest.raises(ValueError):
        bkt.validate(bkt.BktParams(p_guess=0.6, p_slip=0.5))


def test_observe_clamps_extremes():
    params = bkt.BktParams()
    p = bkt.observe(0.01, 1.0, params)
    assert bkt.EPS <= p <= 1 - bkt.EPS
    p0 = bkt.observe(0.99, 0.0, params)
    assert bkt.EPS <= p0 <= 1 - bkt.EPS


def test_observe_hard_limits_match_bayes():
    params = bkt.BktParams(p_guess=0.2, p_slip=0.1, p_learn=0.0, p_init=0.5)
    got = bkt.observe(0.5, 1.0, params)
    assert got == pytest.approx(0.9 * 0.5 / (0.9 * 0.5 + 0.2 * 0.5))


def test_apply_learning_monotone_and_clamped():
    params = bkt.BktParams(p_learn=0.2)
    out = bkt.apply_learning(0.5, params)
    assert out == pytest.approx(0.5 + (1 - 0.5) * 0.2)
    assert out > 0.5
    assert bkt.apply_learning(1 - bkt.EPS, params) <= 1 - bkt.EPS


def test_predict_correct_formula():
    params = bkt.BktParams(p_guess=0.2, p_slip=0.1)
    probs = bkt.predict_correct([0.5], params)
    assert probs[0] == pytest.approx(0.5 * 0.9 + 0.5 * 0.2)


def test_predict_sequence_no_future_leakage():
    """Đổi bất kỳ quan sát nào từ vị trí k trở đi KHÔNG được đổi dự đoán < k."""
    params = bkt.BktParams()
    base = bkt.predict_sequence([1.0, 0.0, 1.0, 0.0, 1.0], params)
    for k in range(1, 5):
        mutated = [1.0, 0.0, 1.0, 0.0, 1.0]
        mutated[k] = 1.0 - mutated[k]
        changed = bkt.predict_sequence(mutated, params)
        for i in range(k):
            assert base[i] == pytest.approx(changed[i]), f"leak tại k={k}, i={i}"


def test_predict_sequence_all_correct_increases():
    params = bkt.BktParams()
    preds = bkt.predict_sequence([1.0] * 6, params)
    assert all(preds[i] <= preds[i + 1] for i in range(len(preds) - 1))


def test_predict_sequence_all_wrong_decreases():
    params = bkt.BktParams()
    preds = bkt.predict_sequence([0.0] * 6, params)
    assert all(preds[i] >= preds[i + 1] for i in range(len(preds) - 1))


def test_soft_observation_converges_to_hard():
    params = bkt.BktParams()
    hard = bkt.predict_sequence([1.0] * 5, params)
    soft = bkt.predict_sequence([0.999999] * 5, params)
    for a, b in zip(hard, soft):
        assert a == pytest.approx(b, abs=1e-4)


def test_brier_bounds():
    assert bkt.brier([1.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)
    assert bkt.brier([0.0, 1.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_fit_grid_is_deterministic_and_returns_train_brier():
    train = [[1.0, 1.0, 0.0, 1.0], [0.0, 0.0, 1.0, 0.0]]
    grid = [bkt.BktParams(p_learn=x) for x in (0.05, 0.2, 0.5)]
    first = bkt.fit_grid(train, grid)
    second = bkt.fit_grid(train, grid)
    assert first[0] == second[0]
    assert first[1] == pytest.approx(second[1])
    assert first[1] >= 0.0
