"""Tests for `pulse agreement` CLI (B2, task J4). Cache-hit test is key."""

import json

TRACE_BODY = (
    'SESSION_ID = "s1"\nMODEL = "m"\nCOST = {"cost_usd": 0.01}\n'
    'TIMELINE = [{"kind": "user_message", "text": "user question 0 about python code"},\n'
    ' {"kind": "user_message", "text": "user question 1 about python code"},\n'
    ' {"kind": "user_message", "text": "user question 2 about python code"},\n'
    ' {"kind": "llm_call", "text": "assistant answer 0 with enough words here"},\n'
    ' {"kind": "llm_call", "text": "assistant answer 1 with enough words here"}]\n'
)

from pulse.signals_deep import PROMPT_VERSION

EMPTY_VERDICTS = json.dumps({"prompt_version": PROMPT_VERSION, "verdicts": []})


def _stubbed_cli(monkeypatch):
    import pulse.agreement_cli as cli
    from pulse.judge import JudgeResult, StubJudge

    monkeypatch.setenv("PULSE_JUDGE_CONTEXT", "16384")  # batch budget knob (ADR 0010)

    calls = {"n": 0}

    class CountingJudge(StubJudge):
        def judge(self, prompt):
            calls["n"] += 1
            return super().judge(prompt)

    def _make(args):
        return CountingJudge([JudgeResult(text=EMPTY_VERDICTS)])

    monkeypatch.setattr(cli, "make_backend", _make)
    return cli, calls


def test_cache_hit_avoids_backend_call(monkeypatch, tmp_path, capsys):
    cli, calls = _stubbed_cli(monkeypatch)
    d = tmp_path / "c"
    d.mkdir()
    (d / "t.py").write_text(TRACE_BODY)
    cache = tmp_path / "cache.json"
    assert cli.main(["--corpus", str(d), "--limit", "5", "--cache", str(cache)]) == 1
    assert calls["n"] == 1
    capsys.readouterr()
    # Second run: cache hit, backend untouched.
    assert cli.main(["--corpus", str(d), "--limit", "5", "--cache", str(cache)]) == 1
    assert calls["n"] == 1
    assert "cache hits" in capsys.readouterr().out.lower()


def test_gate_reports_pending_below_n(monkeypatch, tmp_path, capsys):
    cli, _ = _stubbed_cli(monkeypatch)
    d = tmp_path / "c"
    d.mkdir()
    (d / "t.py").write_text('SESSION_ID = "s1"\nTIMELINE = []\n')
    cli.main(["--corpus", str(d), "--limit", "5", "--cache", str(tmp_path / "c2.json")])
    out = capsys.readouterr().out
    assert "FAIL" in out or "pending" in out.lower()


def test_judge_call_failure_exits_2_names_trace_keeps_cache(monkeypatch, tmp_path, capsys):
    """M0: dead endpoint at record #2 -> exit 2, trace named, #1's verdict flushed."""
    import pulse.agreement_cli as cli
    from pulse.judge import JudgeBackend, JudgeResult

    class FlakyJudge(JudgeBackend):
        model = "flaky"
        base_url = ""

        def __init__(self):
            super().__init__()
            self.n = 0

        def judge(self, prompt):
            self.n += 1
            if self.n == 1:
                return JudgeResult(text=EMPTY_VERDICTS)
            raise ConnectionError("endpoint died mid-batch")

    monkeypatch.setenv("PULSE_JUDGE_CONTEXT", "16384")
    flaky = FlakyJudge()
    monkeypatch.setattr(cli, "make_backend", lambda args: flaky)
    d = tmp_path / "c"
    d.mkdir()
    (d / "t1.py").write_text(TRACE_BODY)
    (d / "t2.py").write_text(TRACE_BODY.replace('"s1"', '"s2"'))
    cache = tmp_path / "cache.json"

    rc = cli.main(["--corpus", str(d), "--limit", "5", "--cache", str(cache)])
    assert rc == 2, "loud failure must exit nonzero naming the trace"
    err = capsys.readouterr().err
    assert "judge call failure" in err and "t2.py" in err
    assert len(json.loads(cache.read_text())) == 1, "per-record flush: #1 intact"

    # Rerun: #1 served from cache, #2 judged fresh, gate FAIL (small n) = 1.
    cli, calls = _stubbed_cli(monkeypatch)
    rc2 = cli.main(["--corpus", str(d), "--limit", "5", "--cache", str(cache)])
    assert rc2 == 1 and calls["n"] == 1, "rerun resumes from cache, not zero"
    assert len(json.loads(cache.read_text())) == 2


def test_failure_drill_script_green():
    """scripts/drill_judge_failure.py proves the contract against a CLOSED port."""
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    r = subprocess.run(
        [sys.executable, "scripts/drill_judge_failure.py"],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo,
        timeout=180,
    )
    assert r.returncode == 0, r.stdout + "\n" + r.stderr
    assert "DRILL PASS" in r.stdout


# ── v2: finding-aware cache VALUE, abstain round-trip, grounding report ──

ABSTAIN_VERDICTS = json.dumps(
    {
        "prompt_version": PROMPT_VERSION,
        "verdicts": [
            {"signal": "correction_quality", "finding": "unscoreable", "penalty": 0},
            {"signal": "goal_completion", "finding": "no", "penalty": 0},
            {"signal": "hallucination", "finding": "no", "penalty": 0},
            {"signal": "context_retention", "finding": "no", "penalty": 0},
        ],
    }
)


def _cli_with_text(monkeypatch, text):
    import pulse.agreement_cli as cli
    from pulse.judge import JudgeResult, StubJudge

    monkeypatch.setenv("PULSE_JUDGE_CONTEXT", "16384")  # batch budget knob (ADR 0010)

    monkeypatch.setattr(cli, "make_backend", lambda args: StubJudge([JudgeResult(text=text)]))
    return cli


def test_cache_value_is_finding_aware_and_abstain_survives_reload(monkeypatch, tmp_path, capsys):
    """G3: v2 cache VALUE = {signal: finding}; an abstain must round-trip
    through disk reload and stay excluded from its kappa pair."""
    cli = _cli_with_text(monkeypatch, ABSTAIN_VERDICTS)
    d = tmp_path / "c"
    d.mkdir()
    (d / "t1.py").write_text(TRACE_BODY)
    cache = tmp_path / "cache.json"

    assert cli.main(["--corpus", str(d), "--limit", "5", "--cache", str(cache)]) == 1
    entries = json.loads(cache.read_text())
    assert len(entries) == 1
    value = next(iter(entries.values()))
    assert value == {
        "correction_quality": "unscoreable",
        "goal_completion": "no",
        "hallucination": "no",
        "context_retention": "no",
    }
    capsys.readouterr()

    # Reload: fresh run; a backend whose CALL would fail -> the abstain
    # came from cache and stays an abstain (never "no").
    class NeverJudge:
        model = "never"
        base_url = ""

        def judge(self, prompt):
            raise AssertionError("cache hit must not reach the backend")

    monkeypatch.setattr(cli, "make_backend", lambda args: NeverJudge())
    rc = cli.main(["--corpus", str(d), "--limit", "5", "--cache", str(cache), "--json"])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["cache_hits"] == 1
    assert out["abstained"]["correction_chain"] == 1  # unscoreable excluded
    assert out["abstained"]["premature_stop"] == 0  # finding=no counted negative
    assert out["pairs"]["correction_chain"]["n"] == 0


def test_absent_verdict_counts_as_abstain_not_no(monkeypatch, tmp_path, capsys):
    """Omission laundering fix: verdicts [] -> abstain on BOTH pairs."""
    cli = _cli_with_text(monkeypatch, EMPTY_VERDICTS)
    d = tmp_path / "c"
    d.mkdir()
    (d / "t1.py").write_text(TRACE_BODY)
    cache = tmp_path / "cache.json"
    assert cli.main(["--corpus", str(d), "--limit", "5", "--cache", str(cache), "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["abstained"] == {"correction_chain": 1, "premature_stop": 1}
    assert out["pairs"]["correction_chain"]["n"] == 0
    assert out["cache_hits"] == 0  # empty findings still cached


def test_grounding_rate_prints_on_fresh_calls(monkeypatch, tmp_path, capsys):
    cli = _cli_with_text(
        monkeypatch,
        json.dumps(
            {
                "prompt_version": PROMPT_VERSION,
                "verdicts": [
                    {
                        "signal": "hallucination",
                        "finding": "yes",
                        "penalty": 10,
                        "evidence": ["user question 0 about python code"],
                    },
                    {
                        "signal": "goal_completion",
                        "finding": "yes",
                        "penalty": 10,
                        "evidence": ["a totally fabricated quote not in the transcript"],
                    },
                ],
            }
        ),
    )
    d = tmp_path / "c"
    d.mkdir()
    (d / "t1.py").write_text(TRACE_BODY)
    assert cli.main(["--corpus", str(d), "--limit", "5", "--cache", str(tmp_path / "cache.json")]) == 1
    out = capsys.readouterr().out
    assert "evidence grounding: 1/2 quotes grounded (50.0%)" in out
    assert "prompt size (fresh calls):" in out and "max=" in out
