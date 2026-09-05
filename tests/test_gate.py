"""Tests for Pulse CI gate (Phase C1)."""

from pulse.gate import compare


def _rec(score, task="coding"):
    return {"score": score, "task_type": task}


def test_pass_when_candidate_matches_baseline():
    recs = [_rec(80), _rec(90)]
    out = compare(recs, [_rec(82), _rec(88)])
    assert out["pass"] is True
    assert out["baseline_mean"] == 85.0
    assert out["candidate_mean"] == 85.0
    assert out["delta"] == 0.0


def test_fail_when_task_mean_drops_beyond_tolerance():
    base = [_rec(90, "coding"), _rec(70, "brainstorm")]
    cand = [_rec(80, "coding"), _rec(70, "brainstorm")]  # coding drops 10
    out = compare(base, cand, tolerance=5.0)
    assert out["pass"] is False
    assert out["detail"]["coding"]["drop"] == 10.0


def test_drop_within_tolerance_passes():
    base = [_rec(90)]
    out = compare(base, [_rec(87)], tolerance=5.0)
    assert out["pass"] is True


def test_overall_means_reported_per_task():
    base = [_rec(90, "coding"), _rec(60, "brainstorm")]
    cand = [_rec(90, "coding"), _rec(60, "brainstorm")]
    out = compare(base, cand)
    assert set(out["detail"]) == {"coding", "brainstorm"}
    assert out["baseline_mean"] == 75.0
