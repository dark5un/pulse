"""Tests for pulse distribution comparison (plan item 2 / A2). Synthetic records."""

from pulse.compare import compare_distributions, summarize


def _rec(score, cost=0.01, task="coding"):
    return {"score": score, "cost_usd": cost, "task_type": task}


def test_summarize_stats():
    s = summarize([80.0, 90.0, 100.0])
    assert s["n"] == 3
    assert s["mean"] == 90.0
    assert s["median"] == 90.0
    assert s["p25"] == 85.0
    assert s["p75"] == 95.0


def test_summarize_empty():
    s = summarize([])
    assert s["n"] == 0
    assert s["mean"] == 0.0


def test_summarize_even_median():
    s = summarize([70.0, 90.0])
    assert s["median"] == 80.0


def test_compare_winner_and_deltas():
    a = [_rec(80, 0.02), _rec(90, 0.02)]
    b = [_rec(70, 0.01), _rec(80, 0.01)]
    out = compare_distributions(a, b)
    assert out["verdict"].startswith("A wins")
    assert out["score_delta"] == 10.0
    assert out["cost_delta"] == 0.01
    assert out["a"]["n"] == 2 and out["b"]["n"] == 2


def test_compare_tie_within_one_point():
    a = [_rec(85), _rec(85)]
    b = [_rec(85), _rec(85)]
    out = compare_distributions(a, b)
    assert "ties" in out["verdict"]


def test_compare_labels_provisional():
    out = compare_distributions([_rec(80)], [_rec(90)])
    assert "provisional" in out["verdict"]
    assert "n=1" in out["verdict"]


def test_compare_empty_side():
    out = compare_distributions([], [_rec(90)])
    assert out["a"]["n"] == 0
    assert "no data" in out["verdict"].lower() or "B" in out["verdict"]
