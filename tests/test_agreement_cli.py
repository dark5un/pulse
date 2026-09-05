"""Tests for `pulse agreement` CLI (B2, task J4). Cache-hit test is key."""

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
