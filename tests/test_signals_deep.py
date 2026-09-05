"""Tests for LLM-judge detectors (B2, task J2). All offline via StubJudge."""

import json


def _backend(*verdicts):
    from pulse.judge import JudgeResult, StubJudge

    return StubJudge(
        [JudgeResult(text=json.dumps({"prompt_version": "v1", "verdicts": list(verdicts)}))]
    )


def test_goal_completion_parses_to_signal():
    from pulse.signals_deep import detect_deep

    msgs = [
        {"role": "user", "content": "please fix the login bug today"},
        {"role": "assistant", "content": "patched auth.py with a regression test"},
    ]
    sigs = detect_deep(
        msgs,
        _backend(
            {
                "signal": "goal_completion",
                "finding": "yes",
                "penalty": 0,
                "evidence": "patched auth.py",
            }
        ),
    )
    assert [s.name for s in sigs] == ["goal_completion"]
    assert sigs[0].evidence and sigs[0].detail.startswith("llm-judge")


def test_unparseable_judge_output_yields_no_signals():
    from pulse.judge import JudgeResult, StubJudge
    from pulse.signals_deep import detect_deep

    sigs = detect_deep(
        [{"role": "user", "content": "hi there friend, how are you doing today?"}],
        StubJudge([JudgeResult(text="not json at all")]),
    )
    assert sigs == []


def test_unknown_signal_names_ignored():
    from pulse.signals_deep import detect_deep

    sigs = detect_deep(
        [{"role": "user", "content": "hello world today please"}],
        _backend({"signal": "mind_reading", "finding": "yes", "penalty": 25, "evidence": "x"}),
    )
    assert sigs == []


def test_correction_quality_targets_user():
    from pulse.signals_deep import detect_deep

    sigs = detect_deep(
        [{"role": "user", "content": "hello world today please"}],
        _backend(
            {
                "signal": "correction_quality",
                "finding": "yes",
                "penalty": 5,
                "evidence": "just no",
            }
        ),
    )
    assert sigs[0].target == "user"
    assert sigs[0].penalty == 5


def test_penalty_clamped_to_25():
    from pulse.signals_deep import detect_deep

    sigs = detect_deep(
        [{"role": "user", "content": "hello world today please"}],
        _backend(
            {
                "signal": "hallucination",
                "finding": "yes",
                "penalty": 999,
                "evidence": "invented",
            }
        ),
    )
    assert sigs[0].penalty == 25
    assert sigs[0].severity == "critical"
