"""Tests for the LLM-judge backend (B2, task J1). All offline."""

from pulse.judge import JudgeResult, StubJudge


def test_stub_judge_returns_scripted_result():
    j = StubJudge([JudgeResult(text='{"verdicts": []}', input_tokens=10, output_tokens=5)])
    out = j.judge("anything")
    assert out.text.startswith("{") and out.input_tokens == 10


def test_stub_judge_repeats_last():
    j = StubJudge([JudgeResult(text="a"), JudgeResult(text="b")])
    assert j.judge("x").text == "a"
    assert j.judge("x").text == "b"
    assert j.judge("x").text == "b"


def test_resolve_api_key_env_chain(monkeypatch):
    from pulse.judge import resolve_api_key

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("HERMES_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert resolve_api_key() == "sk-test"
