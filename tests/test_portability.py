"""Tests for cross-model skill portability (Phase E1). Synthetic records only."""

from pulse.portability import portability


def _rec(model, skills, deadweight=()):
    return {
        "session_id": f"{model}-{sorted(skills)}-{sorted(deadweight)}",
        "model": model,
        "score": 90,
        "penalty": 10,
        "cost_usd": 0.01,
        "task_type": "coding",
        "active_skills": list(skills),
        "signals": [
            {
                "name": "skill_deadweight",
                "severity": "warning",
                "penalty": 8,
                "label": f"Skill '{s}' loaded but unused",
                "evidence": [f"skill '{s}' loaded but unused before corrections"],
            }
            for s in deadweight
        ],
    }


def test_portable_skill_clean_everywhere():
    recs = [_rec("m1", ["skill-a"]), _rec("m2", ["skill-a"]), _rec("m3", ["skill-a"])]
    out = portability(recs)
    assert out["skill-a"]["verdict"] == "portable"
    assert out["skill-a"]["models"] == {"m1": 0.0, "m2": 0.0, "m3": 0.0}


def test_model_specific_skill():
    recs = [
        _rec("m1", ["skill-b"], deadweight=["skill-b"]),
        _rec("m1", ["skill-b"], deadweight=["skill-b"]),
        _rec("m2", ["skill-b"]),
        _rec("m2", ["skill-b"]),
    ]
    out = portability(recs)
    assert out["skill-b"]["verdict"] == "model_specific"
    assert out["skill-b"]["models"]["m1"] == 1.0
    assert out["skill-b"]["models"]["m2"] == 0.0


def test_dead_skill_flagged_everywhere():
    recs = [
        _rec("m1", ["skill-c"], deadweight=["skill-c"]),
        _rec("m2", ["skill-c"], deadweight=["skill-c"]),
        _rec("m3", ["skill-c"], deadweight=["skill-c"]),
    ]
    out = portability(recs)
    assert out["skill-c"]["verdict"] == "dead"


def test_empty_input():
    assert portability([]) == {}


def test_rate_is_flagged_over_loaded():
    recs = [_rec("m1", ["skill-d"], deadweight=["skill-d"]), _rec("m1", ["skill-d"])]
    out = portability(recs)
    assert out["skill-d"]["models"]["m1"] == 0.5
