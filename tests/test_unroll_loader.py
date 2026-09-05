"""Tests for safe unroll trace loading (no execution)."""

from pulse.unroll_loader import UnrollBundle, bundle_to_messages, load_unroll_trace


def test_loader_extracts_messages_and_metadata(tmp_path):
    trace = tmp_path / "trace.py"
    trace.write_text(
        'SESSION_ID = "abc"\nMODEL = "gpt-4o"\n'
        'TIMELINE = [{"kind": "user_message", "offset_ms": 10}]\n'
        'USAGE = {"total_input_tokens": 100}\n'
        'COST = {"model": "gpt-4o", "cost_usd": 0.001}\n'
        'STATE_GRAPH = {"nodes": [], "edges": []}\n'
        'DEPENDENCIES = {}\nACTIVE_SKILLS = ["my-skill"]\n'
        'TOOL_SCHEMAS = []\n'
        'RESPONSE_CACHE = {}\n'
        'raise RuntimeError("MUST NOT EXECUTE")\n'
    )
    bundle = load_unroll_trace(str(trace))
    assert bundle.session_id == "abc"
    assert bundle.cost_usd == 0.001
    assert bundle.active_skills == ["my-skill"]


def test_bundle_to_messages_rebuilds_roles():
    bundle = UnrollBundle(
        timeline=[
            {"kind": "user_message"},
            {"kind": "llm_call"},
            {"kind": "tool_call"},
        ]
    )
    msgs = bundle_to_messages(bundle)
    assert [m["role"] for m in msgs] == ["user", "assistant", "tool"]
