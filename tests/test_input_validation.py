"""WU-2 (PU-2, PU-3): loader and judge-parser hardening.

Loader: malformed constants raise TraceSchemaError naming the offending
field (never bare AttributeError/TypeError); oversized files and deeply
nested literals are rejected before evaluation.
Judge parser: finding must be yes/no with penalty==0 when no; penalties
must be finite; penalty>0 needs non-empty bounded evidence; duplicate
signal names merge deterministically; evidence must be bounded strings.
Dropped verdicts are visible via parse diagnostics.
"""

import json


def _trace(tmp_path, text, name="t.py"):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


# --- Loader: typed schema errors -------------------------------------------


def test_loader_rejects_non_mapping_cost(tmp_path):
    from pulse.unroll_loader import TraceSchemaError, load_unroll_trace

    for bad in ('COST = 1.0\nTIMELINE = []\n', 'COST = "x"\nTIMELINE = []\n'):
        try:
            load_unroll_trace(_trace(tmp_path, bad))
        except TraceSchemaError as e:
            assert "COST" in str(e)
        else:
            raise AssertionError(f"no error for {bad!r}")


def test_loader_rejects_non_list_timeline(tmp_path):
    from pulse.unroll_loader import TraceSchemaError, load_unroll_trace

    for bad in ("TIMELINE = 1\n", "TIMELINE = [1, 2]\n"):
        try:
            load_unroll_trace(_trace(tmp_path, bad))
        except TraceSchemaError as e:
            assert "TIMELINE" in str(e)
        else:
            raise AssertionError(f"no error for {bad!r}")


def test_loader_rejects_bad_usage_and_skills(tmp_path):
    from pulse.unroll_loader import TraceSchemaError, load_unroll_trace

    for bad_field, bad_text in (
        ("USAGE", 'USAGE = []\nTIMELINE = []\n'),
        ("ACTIVE_SKILLS", 'ACTIVE_SKILLS = "a"\nTIMELINE = []\n'),
    ):
        try:
            load_unroll_trace(_trace(tmp_path, bad_text))
        except TraceSchemaError as e:
            assert bad_field in str(e)
        else:
            raise AssertionError(f"no error for {bad_text!r}")


def test_loader_rejects_oversized_file(tmp_path):
    from pulse.unroll_loader import MAX_TRACE_BYTES, TraceSchemaError, load_unroll_trace

    big = tmp_path / "big.py"
    big.write_bytes(b"x = 1\n" * ((MAX_TRACE_BYTES // 6) + 10))
    try:
        load_unroll_trace(str(big))
    except TraceSchemaError as e:
        assert "too large" in str(e)
    else:
        raise AssertionError("oversized file accepted")


def test_loader_rejects_deeply_nested_literal(tmp_path):
    from pulse.unroll_loader import TraceSchemaError, load_unroll_trace

    nested = "TIMELINE = " + "[" * 500 + "]" * 500 + "\n"
    try:
        load_unroll_trace(_trace(tmp_path, nested))
    except TraceSchemaError as e:
        assert "nest" in str(e).lower() or "deep" in str(e).lower() or "TIMELINE" in str(e)
    else:
        raise AssertionError("deeply nested literal accepted")


def test_trace_schema_error_is_value_error():
    from pulse.unroll_loader import TraceSchemaError

    assert issubclass(TraceSchemaError, ValueError)


# --- Judge parser: verdict validation ----------------------------------------


def _parse(text):
    from pulse.signals_deep import parse_verdict_text

    return parse_verdict_text(text)


def _payload(*verdicts):
    return json.dumps({"prompt_version": "v1", "verdicts": list(verdicts)})


def test_parser_drops_garbage_finding():
    from pulse.signals_deep import parse_verdict_text

    result = parse_verdict_text(
        _payload({"signal": "goal_completion", "finding": "garbage", "penalty": 5, "evidence": "x"})
    )
    assert result.signals == []
    assert any("finding" in d for d in result.diagnostics)


def test_parser_drops_no_finding_with_penalty():
    from pulse.signals_deep import parse_verdict_text

    result = parse_verdict_text(
        _payload({"signal": "goal_completion", "finding": "no", "penalty": 10, "evidence": "x"})
    )
    assert result.signals == []
    assert result.diagnostics


def test_parser_drops_penalty_without_evidence():
    from pulse.signals_deep import parse_verdict_text

    result = parse_verdict_text(
        _payload({"signal": "hallucination", "finding": "yes", "penalty": 10, "evidence": ""})
    )
    assert result.signals == []


def test_parser_drops_non_finite_penalty():
    from pulse.signals_deep import parse_verdict_text

    for bad in ("NaN", "Infinity", "-Infinity"):
        result = parse_verdict_text(
            _payload({"signal": "hallucination", "finding": "yes", "penalty": float(bad), "evidence": "x"})
        )
        assert result.signals == [], f"penalty {bad} carried a signal"
    # NaN must not survive max/min into a score-bearing signal either.
    result = parse_verdict_text(
        '{"prompt_version": "v1", "verdicts": [{"signal": "hallucination", "finding": "yes", "penalty": NaN, "evidence": "x"}]}'
    )
    assert result.signals == []


def test_parser_merges_duplicate_signals_deterministically():
    from pulse.signals_deep import parse_verdict_text

    result = parse_verdict_text(
        _payload(
            {"signal": "goal_completion", "finding": "yes", "penalty": 5, "evidence": "first"},
            {"signal": "goal_completion", "finding": "yes", "penalty": 12, "evidence": "second"},
        )
    )
    assert len(result.signals) == 1
    assert result.signals[0].penalty == 12
    assert any("duplicate" in d for d in result.diagnostics)


def test_parser_rejects_non_string_and_oversized_evidence():
    from pulse.signals_deep import parse_verdict_text

    result = parse_verdict_text(
        _payload({"signal": "hallucination", "finding": "yes", "penalty": 5, "evidence": {"not": "a string"}})
    )
    assert result.signals == []
    result = parse_verdict_text(
        _payload({"signal": "hallucination", "finding": "yes", "penalty": 5, "evidence": ["ok", "x" * 5000]})
    )
    assert result.signals == [] or all(len(e) <= 200 for s in result.signals for e in s.evidence)


def test_parser_accepts_evidence_list():
    from pulse.signals_deep import parse_verdict_text

    result = parse_verdict_text(
        _payload({"signal": "hallucination", "finding": "yes", "penalty": 5, "evidence": ["quote one", "quote two"]})
    )
    assert len(result.signals) == 1
    assert result.diagnostics == []


def test_detect_deep_still_returns_signal_list():
    from pulse.judge import JudgeResult, StubJudge
    from pulse.signals_deep import detect_deep

    backend = StubJudge([JudgeResult(text=_payload(
        {"signal": "goal_completion", "finding": "yes", "penalty": 0, "evidence": ""},
    ))])
    sigs = detect_deep([{"role": "user", "content": "hi"}], backend)
    assert isinstance(sigs, list)
