"""Tests for skill ROI ledger (plan item 2b / A3). Synthetic records only.

Correlation, not causation: cards must show task-type mix alongside rates.
"""

from pulse.skills import ledger


def _rec(skills, score=85, cost=0.02, task="coding", signals=()):
    return {
        "session_id": f"{sorted(skills)}-{score}-{task}",
        "model": "m1",
        "score": score,
        "penalty": 100 - score,
        "cost_usd": cost,
        "task_type": task,
        "active_skills": list(skills),
        "signals": list(signals),
    }


def _dw(skill):
    return {
        "name": "skill_deadweight",
        "severity": "warning",
        "penalty": 8,
        "label": f"Skill '{skill}' loaded but unused",
        "evidence": [f"skill '{skill}' loaded but unused before corrections"],
    }


def _corr():
    return {
        "name": "correction_chain",
        "severity": "warning",
        "penalty": 10,
        "label": "correction",
        "evidence": ["no wait, fix that"],
    }


def test_per_skill_card_fields():
    recs = [
        _rec(["skill-a"], score=90, cost=0.01, signals=[_dw("skill-a")]),
        _rec(["skill-a"], score=80, cost=0.03, signals=[_dw("skill-a"), _corr()]),
        _rec([], score=88, cost=0.02),
    ]
    out = ledger(recs)
    card = out["skill-a"]
    assert card["loads"] == 2
    assert card["deadweight_rate"] == 1.0
    assert card["correction_rate"] == 0.5
    assert card["mean_cost"] == 0.02
    assert card["task_mix"] == {"coding": 2}
    # skill-less sessions of same task type as cost baseline
    assert card["baseline_cost_same_task"] == 0.02


def test_task_mix_shown_for_honesty():
    recs = [
        _rec(["skill-b"], task="coding"),
        _rec(["skill-b"], task="brainstorm"),
    ]
    out = ledger(recs)
    assert out["skill-b"]["task_mix"] == {"coding": 1, "brainstorm": 1}


def test_empty_input():
    assert ledger([]) == {}


def test_skill_never_flagged_zero_rates():
    recs = [_rec(["skill-c"], signals=[])]
    out = ledger(recs)
    assert out["skill-c"]["deadweight_rate"] == 0.0
    assert out["skill-c"]["correction_rate"] == 0.0
