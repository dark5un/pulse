"""Tests for LLM-judge detectors (B2, task J2). All offline via StubJudge."""

import json


def _backend(*verdicts):
    from pulse.judge import JudgeResult, StubJudge
    from pulse.signals_deep import PROMPT_VERSION

    return StubJudge(
        [JudgeResult(text=json.dumps({"prompt_version": PROMPT_VERSION, "verdicts": list(verdicts)}))]
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


def test_judge_call_failure_raises_loudly():
    """M0 contract: a backend CALL failure must surface, never read as []."""
    from pulse.judge import JudgeBackend, JudgeResult
    from pulse.signals_deep import JudgeCallError, detect_deep

    class BrokenJudge(JudgeBackend):
        model = "broken"
        base_url = "http://127.0.0.1:1"

        def judge(self, prompt: str) -> JudgeResult:
            raise ConnectionError("connection refused")

    try:
        detect_deep([{"role": "user", "content": "hi there friend"}], BrokenJudge())
        raise AssertionError("expected JudgeCallError")
    except JudgeCallError as e:
        assert "connection refused" in str(e)
        assert "broken" in str(e)


def test_unparseable_output_still_empty_with_diagnostics():
    """Keep semantics: bad OUTPUT is not a call failure — [] + diagnostics."""
    from pulse.judge import JudgeResult, StubJudge
    from pulse.signals_deep import detect_deep, parse_verdict_text

    sigs = detect_deep(
        [{"role": "user", "content": "hi there friend, how are you today?"}],
        StubJudge([JudgeResult(text="```not json```")]),
    )
    assert sigs == []
    res = parse_verdict_text("```not json```")
    assert res.signals == [] and res.diagnostics


# ── v2 schema: unscoreable / absent / grounding (ADR 0006, ML-A4) ────────


def _v2_payload(*verdicts):
    import json

    from pulse.signals_deep import PROMPT_VERSION

    return json.dumps({"prompt_version": PROMPT_VERSION, "verdicts": list(verdicts)})


def test_unscoreable_is_accepted_abstain_without_evidence():
    from pulse.signals_deep import parse_verdict_text

    res = parse_verdict_text(
        _v2_payload({"signal": "correction_quality", "finding": "unscoreable", "penalty": 0})
    )
    assert res.findings == {"correction_quality": "unscoreable"}
    assert res.signals and res.signals[0].penalty == 0
    assert res.signals[0].label == "Judge: unscoreable — correction_quality"


def test_unscoreable_with_penalty_is_forced_to_zero_with_diagnostic():
    from pulse.signals_deep import parse_verdict_text

    res = parse_verdict_text(
        _v2_payload({"signal": "hallucination", "finding": "unscoreable", "penalty": 15, "evidence": "x"})
    )
    assert res.findings == {"hallucination": "unscoreable"}
    assert res.signals[0].penalty == 0
    assert any("abstain forced to 0" in d for d in res.diagnostics)


def test_absent_verdicts_are_visible_as_missing_findings():
    """parse keeps only declared verdicts; absent => abstain downstream."""
    from pulse.signals_deep import parse_verdict_text

    res = parse_verdict_text(
        _v2_payload({"signal": "goal_completion", "finding": "no", "penalty": 0})
    )
    assert res.findings == {"goal_completion": "no"}  # other three ABSENT


def test_v1_payload_is_rejected_by_v2_parser():
    from pulse.signals_deep import parse_verdict_text

    res = parse_verdict_text('{"prompt_version": "v1", "verdicts": []}')
    assert res.signals == [] and res.diagnostics


def test_prompt_head_fully_specifies_abstain_rule():
    from pulse.signals_deep import FINDINGS, PROMPT_VERSION, _prompt_head

    head = _prompt_head()
    assert PROMPT_VERSION in head
    for token in ("unscoreable", "never omit a signal", "thin", "truncated", "verbatim"):
        assert token in head
    assert "yes|no|unscoreable" in head
    assert set(FINDINGS) == {"yes", "no", "unscoreable"}


def test_evidence_grounding_matches_verbatim_quotes():
    from pulse.signals_deep import build_prompt, parse_verdict_text

    msgs = [
        {"role": "user", "content": "deploy the release candidate tonight"},
        {"role": "assistant", "content": "shipping v0.6.0 to prod now"},
    ]
    prompt = build_prompt(msgs)
    res = parse_verdict_text(
        _v2_payload(
            {
                "signal": "hallucination",
                "finding": "yes",
                "penalty": 10,
                "evidence": ["shipping v0.6.0 to prod now"],
            },
            {
                "signal": "goal_completion",
                "finding": "yes",
                "penalty": 8,
                "evidence": ["the assistant invented a unicorn fact here"],
            },
        ),
        prompt=prompt,
    )
    assert res.total_quotes == 2 and res.grounded == 1
    assert any("not grounded" in d for d in res.diagnostics)
    # ungrounded finding is KEPT (visible data), not silently dropped
    assert {s.name for s in res.signals} == {"hallucination", "goal_completion"}


def test_grounding_normalizes_redaction_ellipsis_and_truncation():
    from pulse.signals_deep import _is_grounded

    prompt = "user: contact ops at [REDACTED] and run deploy.sh --force"
    assert _is_grounded("contact ops at [REDACTED] and run deploy.sh", prompt)
    assert _is_grounded("contact ops … deploy.sh --force", prompt)
    assert _is_grounded("contact ops at … and run deploy.sh --for", prompt)
    assert not _is_grounded("contact ops at … and run rollback.sh --force", prompt)


def test_run_judge_exposes_prompt_size_truncation_and_findings():
    from pulse.judge import JudgeResult, StubJudge
    from pulse.signals_deep import TRUNCATION_MARKER, run_judge

    msgs = [
        {"role": "user", "content": "fix the login bug today please thanks"},
        {"role": "assistant", "content": "patched auth.py with a regression test"},
    ]
    from pulse.signals_deep import MAX_PROMPT_CHARS, PromptBudget, build_prompt

    fixed = PromptBudget(MAX_PROMPT_CHARS, None, "explicit")
    backend = StubJudge([JudgeResult(text=_v2_payload())])
    run = run_judge(msgs, backend, budget=fixed)
    assert run.prompt_chars == len(build_prompt(msgs, fixed)) > 0
    assert run.truncated is False
    assert run.findings == {}

    big = [{"role": "user", "content": "x" * 900}] * 40  # over the 12k budget
    backend2 = StubJudge([JudgeResult(text=_v2_payload())])
    run2 = run_judge(big, backend2, budget=fixed)
    assert run2.truncated is True
    assert run2.budget is fixed
    assert TRUNCATION_MARKER in build_prompt(big, fixed)
