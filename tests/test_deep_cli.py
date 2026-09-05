"""Tests for --deep CLI wiring (B2, task J3). StubJudge only, never network."""

import json

TRACE_BODY = (
    'SESSION_ID = "s1"\nMODEL = "m"\nCOST = {"cost_usd": 0.01}\n'
    'TIMELINE = [{"kind": "user_message", "text": "user question 0 about python code"},\n'
    ' {"kind": "user_message", "text": "user question 1 about python code"},\n'
    ' {"kind": "user_message", "text": "user question 2 about python code"},\n'
    ' {"kind": "llm_call", "text": "assistant answer 0 with enough words here"},\n'
    ' {"kind": "llm_call", "text": "assistant answer 1 with enough words here"}]\n'
)


def test_deep_json_includes_judge_section(monkeypatch, tmp_path, capsys):
    import pulse.__main__ as cli
    from pulse.judge import JudgeResult, StubJudge

    trace = tmp_path / "t.py"
    trace.write_text(TRACE_BODY)
    monkeypatch.setattr(
        cli,
        "OpenAIJudge",
        lambda **kw: StubJudge(
            [JudgeResult(text='{"prompt_version": "v1", "verdicts": []})')]
        ),
    )
    monkeypatch.setattr(
        "sys.argv", ["pulse", "--unroll", str(trace), "--deep", "--json"]
    )
    try:
        cli.main()
    except SystemExit as e:
        assert e.code in (0, None)
    out_text = capsys.readouterr().out
    out = json.loads(out_text[out_text.index("{"):])
    assert "deep" in out and out["deep"]["model"] in ("gpt-4o-mini", "stub")


def test_no_deep_flag_has_no_judge_section(monkeypatch, tmp_path, capsys):
    import pulse.__main__ as cli

    trace = tmp_path / "t.py"
    trace.write_text(TRACE_BODY)
    monkeypatch.setattr("sys.argv", ["pulse", "--unroll", str(trace), "--json"])
    try:
        cli.main()
    except SystemExit as e:
        assert e.code in (0, None)
    out = json.loads(capsys.readouterr().out)
    assert "deep" not in out
