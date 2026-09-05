"""Tests for unroll-native detectors (latency, cost, skill deadweight)."""

from pulse.signals_unroll import detect_cost, detect_latency, detect_skill_deadweight
from pulse.unroll_loader import UnrollBundle


def test_latency_flags_slow_tool_step():
    bundle = UnrollBundle(timeline=[
        {"kind": "tool_call", "offset_ms": 10, "duration_ms": 450},
        {"kind": "tool_call", "offset_ms": 500, "duration_ms": 9000},
    ])
    sigs = detect_latency(bundle)
    assert any(s.name == "latency_regression" for s in sigs)
    assert "9000" in sigs[0].evidence[0]


def test_latency_ignores_fast_steps():
    bundle = UnrollBundle(timeline=[
        {"kind": "tool_call", "offset_ms": 10, "duration_ms": 450},
    ])
    assert detect_latency(bundle) == []


def test_cost_flags_over_ceiling():
    bundle = UnrollBundle(cost_usd=6.00)
    sigs = detect_cost(bundle, "coding")
    assert any(s.name == "cost_anomaly" for s in sigs)
    assert "cost_usd=$6.00" in sigs[0].evidence[0]


def test_cost_passes_under_ceiling():
    bundle = UnrollBundle(cost_usd=0.10)
    assert detect_cost(bundle, "coding") == []
    assert detect_cost(bundle, "brainstorm") == []


def test_cost_brainstorm_ceiling():
    bundle = UnrollBundle(cost_usd=0.75)
    sigs = detect_cost(bundle, "brainstorm")
    assert any(s.name == "cost_anomaly" for s in sigs)


def test_skill_deadweight_warns_with_correction():
    bundle = UnrollBundle(
        active_skills=["pdf-skill"],
        timeline=[{"kind": "user_message"}, {"kind": "llm_call"}],
    )
    messages = [
        {"role": "user", "content": "summarize this report please"},
        {"role": "assistant", "content": "here it is"},
        {"role": "user", "content": "write a python script to parse it"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "no, that's not right, redo it"},
        {"role": "assistant", "content": "fixed"},
    ]
    sigs = detect_skill_deadweight(bundle, messages)
    assert any(s.name == "skill_deadweight" and s.severity == "warning" for s in sigs)
    assert "pdf-skill" in sigs[0].evidence[0]


def test_skill_deadweight_info_without_correction():
    bundle = UnrollBundle(
        active_skills=["pdf-skill"],
        timeline=[{"kind": "user_message"}, {"kind": "llm_call"}],
    )
    messages = [
        {"role": "user", "content": "hello there friend"},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "tell me a story please"},
        {"role": "assistant", "content": "once upon a time"},
        {"role": "user", "content": "thanks, nice story"},
        {"role": "assistant", "content": "you are welcome"},
    ]
    sigs = detect_skill_deadweight(bundle, messages)
    assert len(sigs) == 1 and sigs[0].severity == "info"


def test_skill_deadweight_none_when_tools_used():
    bundle = UnrollBundle(
        active_skills=["pdf-skill"],
        timeline=[{"kind": "tool_call", "duration_ms": 10}],
    )
    assert detect_skill_deadweight(bundle, []) == []


def test_skill_deadweight_none_without_skills():
    assert detect_skill_deadweight(UnrollBundle(), []) == []
