"""Tests for `pulse --unroll <trace.py>` CLI mode."""

import sys

from pulse.__main__ import main


def _write_trace(path):
    entries = []
    for i in range(3):
        entries.append(f'{{"kind": "user_message", "text": "user question {i} about python code"}}')
    for i in range(2):
        entries.append(f'{{"kind": "llm_call", "text": "assistant answer {i}"}}')
    path.write_text(
        'SESSION_ID = "cli-fixture"\nMODEL = "gpt-4o"\n'
        f"TIMELINE = [{', '.join(entries)}]\n"
        'USAGE = {"total_input_tokens": 50}\n'
        'COST = {"model": "gpt-4o", "cost_usd": 0.002}\n'
        'STATE_GRAPH = {"nodes": [], "edges": []}\n'
        "DEPENDENCIES = {}\nACTIVE_SKILLS = []\n"
        "TOOL_SCHEMAS = []\n"
        "RESPONSE_CACHE = {}\n"
    )


def test_unroll_cli_scores_fixture_trace(tmp_path, capsys):
    trace = tmp_path / "trace.py"
    _write_trace(trace)
    sys.argv = ["pulse", "--unroll", str(trace)]
    main()
    out = capsys.readouterr().out
    assert "Pulse" in out


def test_unroll_cli_json_emits_score(tmp_path, capsys):
    import json

    trace = tmp_path / "trace.py"
    _write_trace(trace)
    sys.argv = ["pulse", "--unroll", str(trace), "--json"]
    main()
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert "signals" in payload and "metrics" in payload
