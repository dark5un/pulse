"""Tests for red-team calmness ranking (Phase D2). Synthetic records only."""

from pulse.redteam import calmness


def _rec(model, score, signals=()):
    return {
        "session_id": f"{model}-{score}",
        "model": model,
        "score": score,
        "penalty": 100 - score,
        "cost_usd": 0.01,
        "task_type": "chat",
        "signals": [{"name": n} for n in signals],
    }


def test_ranks_calmest_first_by_mean_score():
    recs = {
        "shaky": [_rec("shaky", 60, ["frustration"]), _rec("shaky", 70)],
        "calm": [_rec("calm", 95), _rec("calm", 90)],
    }
    out = calmness(recs)
    assert [r["model"] for r in out] == ["calm", "shaky"]
    assert out[0]["mean_score"] == 92.5


def test_reports_per_10_session_signal_rates():
    recs = {"m": [_rec("m", 80, ["frustration", "correction_chain"]) for _ in range(5)]}
    out = calmness(recs)
    row = out[0]
    assert row["sessions"] == 5
    assert row["frustration_per_10"] == 10.0
    assert row["correction_chain_per_10"] == 10.0
    assert row["reasoning_loop_per_10"] == 0.0


def test_empty_input():
    assert calmness({}) == []
