"""P5.1 eval — split không leakage, metric cơ bản, gate trung thực."""

from datetime import UTC, datetime, timedelta

from app.services import bkt
from evals import bkt_eval as ev


def test_split_by_user_is_disjoint_and_deterministic():
    keys = [f"u{i}:s" for i in range(10)]
    train, test = ev.split_by_user(keys, ratio=0.7)
    assert train.isdisjoint(test)
    assert train | test == set(keys)
    assert ev.split_by_user(keys, ratio=0.7) == (train, test)
    assert len(test) == 3


def test_split_by_time_is_disjoint():
    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    rows = [(f"k{i}", t0 + timedelta(hours=i)) for i in range(6)]
    train, test = ev.split_by_time(rows, cutoff=t0 + timedelta(hours=3))
    assert train.isdisjoint(test)
    assert test == {"k3", "k4", "k5"}


def test_evaluate_reports_zero_leakage_and_metrics():
    train = [[1.0, 1.0, 0.0, 1.0], [1.0, 0.0, 1.0, 1.0]]
    test = [[1.0, 1.0, 1.0], [0.0, 1.0, 1.0]]
    res = ev.evaluate(train, test)
    for key in (
        "brierBkt",
        "brierBaseline",
        "logLossBkt",
        "aucBkt",
        "aucBaseline",
        "eceBkt",
        "driftBrier",
        "nTest",
        "leakage",
    ):
        assert key in res
    assert res["leakage"] == 0
    assert res["nTest"] == 6


def test_evaluate_empty_test_is_safe():
    res = ev.evaluate([[1.0, 1.0]], [])
    assert res["nTest"] == 0
    assert res["aucBkt"] is None
    assert res["brierBkt"] is None


def test_simulate_is_deterministic_and_labelled():
    params = bkt.BktParams()
    a = ev.simulate(seed=7, users=3, per_user=5, params=params)
    b = ev.simulate(seed=7, users=3, per_user=5, params=params)
    assert [s.key for s in a] == [s.key for s in b]
    assert [s.events for s in a] == [s.events for s in b]
    assert len(a) == 3 and all(len(s.events) == 5 for s in a)


def test_simulate_mismatched_model_does_not_beat_baseline():
    params = bkt.BktParams(p_learn=0.0, p_init=0.5, p_guess=0.2, p_slip=0.1)
    seqs = ev.simulate(seed=3, users=8, per_user=10, params=params, force_correct=True)
    half = len(seqs) // 2
    res = ev.evaluate([s.events for s in seqs[:half]], [s.events for s in seqs[half:]])
    assert res["leakage"] == 0
    assert res["brierBkt"] <= 0.25


def test_decide_gate_insufficient_when_too_few():
    result = {"nSequencesTrain": 0, "nSequencesTest": 0, "nEvents": 0}
    gate = ev.decide_gate(result, {"min_sequences": 30, "min_events": 300})
    assert gate["status"] == "insufficient_data"
    assert gate["gate"] == "NOT_MET"
    assert gate["reasons"]


def test_decide_gate_requires_better_brier():
    result = {
        "nSequencesTrain": 20,
        "nSequencesTest": 20,
        "nEvents": 600,
        "brierBkt": 0.30,
        "brierBaseline": 0.20,
        "eceBkt": 0.05,
        "aucBkt": 0.7,
        "driftBrier": 0.01,
        "leakage": 0,
    }
    gate = ev.decide_gate(result, {"min_sequences": 10, "min_events": 100})
    assert gate["gate"] == "NOT_MET"
    assert any("brier" in r.lower() for r in gate["reasons"])


def test_decide_gate_passes_when_all_criteria_met():
    result = {
        "nSequencesTrain": 20,
        "nSequencesTest": 20,
        "nEvents": 600,
        "brierBkt": 0.10,
        "brierBaseline": 0.20,
        "eceBkt": 0.05,
        "aucBkt": 0.75,
        "driftBrier": 0.01,
        "leakage": 0,
    }
    gate = ev.decide_gate(result, {"min_sequences": 10, "min_events": 100})
    assert gate["gate"] == "PASS"
    assert gate["status"] == "evaluated"
