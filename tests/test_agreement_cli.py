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

EMPTY_VERDICTS = '{"prompt_version": "v1", "verdicts": []}'


def _stubbed_cli(monkeypatch):
    import pulse.agreement_cli as cli
    from pulse.judge import JudgeResult, StubJudge

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
