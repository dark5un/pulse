"""Tests for trace leaderboard (Phase B1)."""

from pulse.leaderboard import rank_traces


def _rec(sid, model, score, task="coding", cost=0.01, signals=None):
    return {
        "session_id": sid,
        "model": model,
        "score": score,
        "penalty": 100 - score,
        "cost_usd": cost,
        "task_type": task,
        "signals": signals or [],
    }


def test_empty_input():
    assert rank_traces([]) == {}


def test_top_bottom_3_per_task_type_with_anonymized_entries():
    recs = [_rec(f"s{i}", "m1", 90 - i, cost=0.01 + i * 0.001) for i in range(7)]
    out = rank_traces(recs)
    assert set(out) == {"coding"}
    assert len(out["coding"]["best"]) == 3
    assert len(out["coding"]["worst"]) == 3
    assert out["coding"]["best"][0]["score"] == 90
    assert out["coding"]["worst"][0]["score"] == 84
    entry = out["coding"]["best"][0]
    assert set(entry) == {"id_hash", "model", "score", "signals"}
    assert len(entry["id_hash"]) == 12
    assert "session_id" not in entry


def test_ties_broken_by_lower_cost():
    recs = [_rec("a", "m1", 80, cost=0.05), _rec("b", "m1", 80, cost=0.01)]
    out = rank_traces(recs)
    import hashlib

    cheap = hashlib.sha256(b"b").hexdigest()[:12]
    assert out["coding"]["best"][0]["id_hash"] == cheap


def test_groups_by_task_type():
    recs = [_rec("a", "m1", 80, task="coding"), _rec("b", "m1", 70, task="brainstorm")]
    out = rank_traces(recs)
    assert set(out) == {"coding", "brainstorm"}
