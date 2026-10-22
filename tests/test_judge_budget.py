"""Decision 11 / ADR 0010+0013: model-derived judge prompt budget.

Resolution order (loud, never assumed): explicit param (--judge-context /
manifest field) -> PULSE_JUDGE_CONTEXT env -> read-only GET probe of the
pinned endpoint's /v1/models metadata -> PULSE_JUDGE_MAX_PROMPT_CHARS
explicit fallback -> JudgeBudgetError. Provider over-long rejections raise
JudgeContextOverflow (loud), never a silent server-side clip. Localhost
fake servers only — no network, no model service (ADR 0007).
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pulse.judge import JudgeBackend, JudgeResult


class _FakeEndpoint:
    """localhost stand-in: serves (or omits) /v1/models metadata and
    answers /chat/completions per script."""

    def __init__(self, models_payload=None, completion_status=200, completion_body=""):
        self.models_payload = models_payload
        self.completion_status = completion_status
        self.completion_body = completion_body
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, code, body):
                raw = body.encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == "/v1/models" and outer.models_payload is not None:
                    self._send(200, json.dumps(outer.models_payload))
                else:
                    self._send(404, "{}")

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                self._send(outer.completion_status, outer.completion_body)

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class _Backend(JudgeBackend):
    """Minimal JudgeBackend stub with an optional context_window probe."""

    def __init__(self, base_url: str = "", ctx: int | None = None) -> None:
        super().__init__()
        self.model = "test-backend"
        self.base_url = base_url
        self._ctx = ctx

    def judge(self, prompt: str) -> JudgeResult:
        return JudgeResult(text="{}")

    def context_window(self) -> int | None:
        return self._ctx


@pytest.fixture
def no_budget_env(monkeypatch):
    for var in ("PULSE_JUDGE_CONTEXT", "PULSE_JUDGE_MAX_PROMPT_CHARS", "PULSE_JUDGE_RESERVE_TOKENS"):
        monkeypatch.delenv(var, raising=False)


def test_env_context_derives_budget(no_budget_env, monkeypatch):
    from pulse.signals_deep import resolve_prompt_budget

    monkeypatch.setenv("PULSE_JUDGE_CONTEXT", "32768")

    pb = resolve_prompt_budget(_Backend())
    assert pb.source == "env" and pb.context_window_tokens == 32768
    assert pb.budget_chars == (32768 - 1536) * 4  # window minus reserved headroom


def test_explicit_param_wins_over_env(no_budget_env, monkeypatch):
    from pulse.signals_deep import resolve_prompt_budget

    monkeypatch.setenv("PULSE_JUDGE_CONTEXT", "32768")

    pb = resolve_prompt_budget(_Backend(), explicit_context_tokens=8192)
    assert pb.source == "explicit" and pb.context_window_tokens == 8192


def test_probe_used_when_no_config(no_budget_env):
    from pulse.signals_deep import resolve_prompt_budget

    pb = resolve_prompt_budget(_Backend(ctx=16384))
    assert pb.source == "probe" and pb.budget_chars == (16384 - 1536) * 4


def test_loud_error_names_knobs_when_nothing_configured(no_budget_env):
    from pulse.signals_deep import JudgeBudgetError, resolve_prompt_budget

    with pytest.raises(JudgeBudgetError) as ei:
        resolve_prompt_budget(_Backend(base_url="http://127.0.0.1:1"))
    msg = str(ei.value)
    assert "PULSE_JUDGE_CONTEXT" in msg and "PULSE_JUDGE_MAX_PROMPT_CHARS" in msg
    assert "/v1/models" in msg


def test_config_fallback_env_is_explicit_not_assumed(no_budget_env, monkeypatch):
    from pulse.signals_deep import resolve_prompt_budget

    monkeypatch.setenv("PULSE_JUDGE_MAX_PROMPT_CHARS", "9000")

    pb = resolve_prompt_budget(_Backend())
    assert pb.source == "config-fallback" and pb.budget_chars == 9000


def test_invalid_env_is_loud(no_budget_env, monkeypatch):
    from pulse.signals_deep import JudgeBudgetError, resolve_prompt_budget

    monkeypatch.setenv("PULSE_JUDGE_CONTEXT", "huge")

    with pytest.raises(JudgeBudgetError):
        resolve_prompt_budget(_Backend())


def test_reserve_override_and_too_small_window(no_budget_env, monkeypatch):
    from pulse.signals_deep import JudgeBudgetError, budget_from_context

    monkeypatch.setenv("PULSE_JUDGE_RESERVE_TOKENS", "512")
    assert budget_from_context(4096) == (4096 - 512) * 4
    with pytest.raises(JudgeBudgetError):
        budget_from_context(400)  # window smaller than headroom: refuse


def test_default_budget_is_stated_static_fallback(no_budget_env):
    from pulse.signals_deep import MAX_PROMPT_CHARS, default_prompt_budget

    pb = default_prompt_budget()
    assert pb.source == "static-fallback" and pb.budget_chars == MAX_PROMPT_CHARS


def test_model_derived_budget_reduces_truncation():
    from pulse.signals_deep import PromptBudget, _compose_prompt, build_prompt

    msgs = [{"role": "user", "content": "x" * 900}] * 40  # >12k body
    default_prompt, truncated_default = _compose_prompt(msgs, 12_000)
    big_prompt, truncated_big = _compose_prompt(msgs, 60_000)
    assert truncated_default is True and "transcript truncated" in default_prompt
    assert truncated_big is False and "transcript truncated" not in big_prompt
    assert len(build_prompt(msgs, PromptBudget(5_000, None, "explicit"))) <= 5_000


# ── OpenAIJudge: probe + provider rejection (localhost fakes only) ────────


def test_context_window_probe_reads_metadata():
    from pulse.judge import OpenAIJudge

    ep = _FakeEndpoint(
        models_payload={"data": [{"id": "my-model", "llama_cpp.n_ctx": 16384}]}
    )
    try:
        assert OpenAIJudge(model="my-model", base_url=ep.url).context_window() == 16384
    finally:
        ep.stop()


def test_context_window_probe_none_without_metadata():
    from pulse.judge import OpenAIJudge

    ep = _FakeEndpoint(models_payload={"data": [{"id": "my-model"}]})
    try:
        assert OpenAIJudge(model="my-model", base_url=ep.url).context_window() is None
    finally:
        ep.stop()


def test_context_window_probe_none_on_dead_port():
    from pulse.judge import OpenAIJudge

    # Bind then close: guaranteed-closed localhost port, no external network.
    probe_only = _FakeEndpoint(models_payload={"data": []})
    url = probe_only.url
    probe_only.stop()
    assert OpenAIJudge(model="m", base_url=url).context_window() is None


def test_provider_overlong_rejection_is_loud(monkeypatch):
    from pulse.judge import JudgeContextOverflow, OpenAIJudge

    monkeypatch.setenv("PULSE_API_KEY", "drill-dummy-never-real")
    body = json.dumps(
        {"error": {"message": "exceeded context size, try reducing prompt", "code": "context_length_exceeded"}}
    )
    ep = _FakeEndpoint(completion_status=400, completion_body=body)
    try:
        judge = OpenAIJudge(model="m", base_url=ep.url)
        with pytest.raises(JudgeContextOverflow) as ei:
            judge.judge("x" * 100)
        assert "over-long" in str(ei.value)
    finally:
        ep.stop()


def test_run_judge_wraps_overflow_loudly(monkeypatch):
    from pulse.judge import OpenAIJudge
    from pulse.signals_deep import JudgeCallError, run_judge

    monkeypatch.setenv("PULSE_API_KEY", "drill-dummy-never-real")
    body = json.dumps({"error": {"message": "prompt is too long for model context", "code": "context_length_exceeded"}})
    ep = _FakeEndpoint(completion_status=400, completion_body=body)
    try:
        from pulse.signals_deep import PromptBudget

        judge = OpenAIJudge(model="m", base_url=ep.url)
        with pytest.raises(JudgeCallError) as ei:
            run_judge(
                [{"role": "user", "content": "hi there friend please"}],
                judge,
                budget=PromptBudget(50_000, 16384, "explicit"),
            )
        msg = str(ei.value)
        assert "over-long" in msg and "PULSE_JUDGE_CONTEXT" in msg
    finally:
        ep.stop()
    # and the budget resolution itself refused a dead metadata path:
    ep2 = _FakeEndpoint(models_payload=None)  # 404 on /v1/models
    try:
        judge2 = OpenAIJudge(model="m", base_url=ep2.url)
        import os

        assert judge2.context_window() is None or os.environ.get("PULSE_JUDGE_CONTEXT")
    finally:
        ep2.stop()


# ── CLI integration: budget refusal + explicit knob ──────────────────────


TRACE_BODY = (
    'SESSION_ID = "s1"\nMODEL = "m"\nCOST = {"cost_usd": 0.01}\n'
    'TIMELINE = [{"kind": "user_message", "text": "user question 0 about python code"},\n'
    ' {"kind": "user_message", "text": "user question 1 about python code"},\n'
    ' {"kind": "user_message", "text": "user question 2 about python code"},\n'
    ' {"kind": "llm_call", "text": "assistant answer 0 with enough words here"},\n'
    ' {"kind": "llm_call", "text": "assistant answer 1 with enough words here"}]\n'
)


def _stub_backend():
    from pulse.judge import JudgeResult, StubJudge

    return StubJudge(
        [JudgeResult(text=json.dumps({"prompt_version": _pv(), "verdicts": []}))]
    )


def _pv():
    from pulse.signals_deep import PROMPT_VERSION

    return PROMPT_VERSION


def test_agreement_cli_refuses_without_budget(monkeypatch, tmp_path, capsys, no_budget_env):
    import pulse.agreement_cli as cli

    monkeypatch.setattr(cli, "make_backend", lambda args: _stub_backend())
    d = tmp_path / "c"
    d.mkdir()
    (d / "t1.py").write_text(TRACE_BODY)
    rc = cli.main(["--corpus", str(d), "--limit", "5", "--cache", str(tmp_path / "cache.json")])
    assert rc == 2
    err = capsys.readouterr().err
    assert "judge budget failure" in err and "PULSE_JUDGE_CONTEXT" in err


def test_agreement_cli_explicit_context_source(monkeypatch, tmp_path, capsys, no_budget_env):
    import pulse.agreement_cli as cli

    monkeypatch.setattr(cli, "make_backend", lambda args: _stub_backend())
    d = tmp_path / "c"
    d.mkdir()
    (d / "t1.py").write_text(TRACE_BODY)
    rc = cli.main(
        ["--corpus", str(d), "--limit", "5", "--cache", str(tmp_path / "cache.json"),
         "--judge-context", "16384"]
    )
    assert rc == 1  # gate FAIL (small n), budget fine
    assert "judge prompt budget: 59392 chars (source=explicit" in capsys.readouterr().err
