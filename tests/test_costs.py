"""Tests for cost attribution join-side rollup (plan item 6 / C2-b).

No capture change: session_id -> team comes from a CSV registry the team
already has; unknown sessions fall into "unmapped", never silently dropped.
"""

import csv

from pulse.costs import load_mapping, rollup


def _rec(sid, cost, task="coding"):
    return {"session_id": sid, "cost_usd": cost, "task_type": task,
            "score": 90, "model": "m"}


def _csv(tmp_path, rows):
    p = tmp_path / "sessions.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["session_id", "team"])
        w.writerows(rows)
    return str(p)


def test_load_mapping(tmp_path):
    m = load_mapping(_csv(tmp_path, [["s1", "team-a"], ["s2", "team-b"]]))
    assert m == {"s1": "team-a", "s2": "team-b"}


def test_rollup_groups_and_sums(tmp_path):
    m = load_mapping(_csv(tmp_path, [["s1", "team-a"], ["s2", "team-a"], ["s3", "team-b"]]))
    out = rollup([_rec("s1", 0.02), _rec("s2", 0.03), _rec("s3", 0.10)], m)
    assert out["team-a"]["total_usd"] == 0.05
    assert out["team-a"]["sessions"] == 2
    assert out["team-b"]["total_usd"] == 0.10
    assert "unmapped" not in out


def test_rollup_unmapped_bucket(tmp_path):
    m = load_mapping(_csv(tmp_path, [["s1", "team-a"]]))
    out = rollup([_rec("s1", 0.02), _rec("ghost", 0.05)], m)
    assert out["unmapped"]["sessions"] == 1
    assert out["unmapped"]["total_usd"] == 0.05


def test_rollup_per_task_split(tmp_path):
    m = load_mapping(_csv(tmp_path, [["s1", "team-a"]]))
    out = rollup([_rec("s1", 0.02, "coding"), _rec("s1", 0.04, "brainstorm")], m)
    assert out["team-a"]["by_task"] == {"coding": 0.02, "brainstorm": 0.04}


def test_rollup_empty():
    assert rollup([], {}) == {}
