"""Tests for the Hermes Pulse plugin.

Tests that the /pulse slash command handler renders correctly
without needing a live Hermes session or state.db.
"""

import sys
from pathlib import Path

# Add pulse project src to path
pulse_src = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(pulse_src))

# Import the plugin module — this is what we're testing
from pulse import plugin as plugin_module
from pulse.models import Signal, SignalResult
from pulse.signals import extract_signals

plugin = plugin_module

# Shared test metrics
METRICS = {
    "total_turns": 42, "total_tokens": 12000, "tool_call_count": 15,
    "read_edit_ratio": 3.5, "user_turns": 8, "agent_turns": 8,
    "reads": 10, "edits": 3, "tool_names": ["read_file", "write_file"],
    "task_type": "coding", "user_texts": [], "agent_texts": [],
}


# ─── _render_card tests ──────────────────────────────────────────────────

def test_render_card_green():
    """Sessions with no signals should show GREEN status."""
    result = SignalResult(signals=[], metrics=METRICS)
    card = plugin._render_card(result, [], "coding", "deepseek/deepseek-v4-flash")
    assert "Pulse" in card
    assert "GREEN" in card
    assert "42" in card
    assert "deepseek" in card


def test_render_card_red():
    """Sessions with high penalty should show RED status."""
    m = dict(METRICS)
    m["total_turns"] = 20
    m["total_tokens"] = 5000
    m["tool_call_count"] = 10
    signals_flat = [
        {"name": "correction_chain", "target": "user", "severity": "warning",
         "penalty": 20, "label": "3 consecutive correction turns",
         "evidence": ["no, that's wrong", "no, still not"]},
        {"name": "tool_error", "target": "agent", "severity": "warning",
         "penalty": 15, "label": "Tool returned an explicit error",
         "evidence": ["Error: connection refused"]},
        {"name": "tool_error", "target": "agent", "severity": "warning",
         "penalty": 15, "label": "Tool returned an explicit error",
         "evidence": ["Error: timeout"]},
    ]
    result = SignalResult(signals=[], metrics=m)
    card = plugin._render_card(result, signals_flat, "coding", "deepseek/deepseek-v4-flash")
    assert "RED" in card
    assert "[-]" in card
    assert "correction" in card or "no, that's wrong" in card


def test_render_card_coaching_appears():
    """Coaching tips should appear when signals are present."""
    signals_flat = [
        {"name": "correction_chain", "target": "user", "severity": "warning",
         "penalty": 12, "label": "correction chain", "evidence": []},
        {"name": "tool_error", "target": "agent", "severity": "warning",
         "penalty": 8, "label": "tool error", "evidence": []},
    ]
    result = SignalResult(signals=[], metrics=METRICS)
    card = plugin._render_card(result, signals_flat, "coding", "test-model")
    assert "Coaching" in card
    assert "use X approach" in card


def test_render_card_no_coaching_when_clean():
    """Clean sessions should show green status but no coaching section."""
    result = SignalResult(signals=[], metrics=METRICS)
    card = plugin._render_card(result, [], "coding", "test-model")
    assert "GREEN" in card
    assert "Coaching" not in card


def test_render_card_shows_evidence():
    """Signals with evidence should show the evidence text."""
    signals_flat = [
        {"name": "frustration", "target": "user", "severity": "warning",
         "penalty": 12, "label": "Frustration signals in 2 turns",
         "evidence": ["you're so lazy, do it properly"]},
    ]
    result = SignalResult(signals=[], metrics=METRICS)
    card = plugin._render_card(result, signals_flat, "coding", "test-model")
    assert "lazy" in card


# ─── _handle_pulse tests ─────────────────────────────────────────────────

def test_handle_pulse_no_session():
    """Without a session, handle_pulse should return error message."""
    # When no state.db or session exists, it should return a message
    result = plugin._handle_pulse("")
    assert isinstance(result, str)
    assert len(result) > 0


def test_handle_pulse_returns_string():
    """handle_pulse should always return a string."""
    result = plugin._handle_pulse("--json")
    assert isinstance(result, str)


# ─── register(ctx) tests ─────────────────────────────────────────────────

def test_register_calls_register_command():
    """register() should call ctx.register_command with 'pulse'."""
    registered = {}

    class FakeCtx:
        def register_command(self, name, handler, description, args_hint=""):
            registered["name"] = name
            registered["handler"] = handler
            registered["description"] = description
            registered["args_hint"] = args_hint

    plugin.register(FakeCtx())
    assert registered["name"] == "pulse"
    assert registered["handler"] is not None
    assert "session" in registered["description"].lower()
    # Verify handler returns a string when called
    result = registered["handler"]("")
    assert isinstance(result, str)


# ─── Integration: extract_signals round-trip ─────────────────────────────

def test_pulse_imports_work():
    """The pulse project imports should resolve correctly."""
    from pulse.models import SignalResult
    assert extract_signals is not None
    assert Signal is not None
    assert SignalResult is not None

# ─── /pulse deep via ctx.llm ─────────────────────────────────────────────

import json as _json


class _FakeUsage:
    input_tokens = 120
    output_tokens = 30
    total_tokens = 150
    cost_usd = 0.001


class _FakeLlmResult:
    text = _json.dumps({"prompt_version": "v1", "verdicts": [
        {"signal": "goal_completion", "finding": "yes", "penalty": 0,
         "evidence": "task done"},
    ]})
    provider = "openrouter"
    model = "meta/muse-spark-1.3"
    usage = _FakeUsage()


class _FakeLlm:
    def __init__(self):
        self.calls = []

    def complete_structured(self, **kw):
        self.calls.append(kw)
        return _FakeLlmResult()


class _FakeCtxWithLlm:
    def __init__(self):
        self.llm = _FakeLlm()

    def register_command(self, name, handler, description, args_hint=""):
        self.handler = handler


def _seed_session(monkeypatch, tmp_path):
    """Seed a state.db session with enough turns to pass the minimum guard.

    NOTE: conftest's autouse isolated_hermes_home already points HERMES_HOME
    at tmp_path/hermes — seed THERE, not tmp_path root.
    """
    import sqlite3
    import time

    from pulse.paths import state_db

    db = state_db()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    msgs = []
    for i in range(3):
        msgs.append(("user", f"user question {i} about python code please"))
        msgs.append(("assistant", f"assistant answer {i} with enough detail here"))
    msgs.append(("user", "thanks, that solves it"))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sessions "
        "(id TEXT PRIMARY KEY, model TEXT, last_activity_at REAL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS messages "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, "
        "content TEXT, tool_calls TEXT, tool_name TEXT)"
    )
    conn.execute(
        "INSERT OR REPLACE INTO sessions VALUES (?, ?, ?)",
        ("sess-deep-1", "m", time.time()),
    )
    conn.executemany(
        "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
        [("sess-deep-1", role, content) for role, content in msgs],
    )
    conn.commit()
    conn.close()


def test_pulse_deep_runs_judge_and_reports_tokens(monkeypatch, tmp_path):
    ctx = _FakeCtxWithLlm()
    plugin.register(ctx)
    _seed_session(monkeypatch, tmp_path)
    out = ctx.handler("deep")
    assert "judge" in out.lower()
    assert "150" in out  # total tokens reported
    assert len(ctx.llm.calls) == 1
    call = ctx.llm.calls[0]
    assert call.get("temperature") == 0.0
    assert call.get("json_mode") is True


def test_pulse_deep_without_llm_lane_explains(monkeypatch, tmp_path):
    class _NoLlmCtx:
        def register_command(self, name, handler, description, args_hint=""):
            self.handler = handler

    ctx = _NoLlmCtx()
    plugin.register(ctx)
    _seed_session(monkeypatch, tmp_path)
    out = ctx.handler("deep")
    assert "not available" in out.lower()


def test_pulse_deep_judge_failure_is_loud(monkeypatch, tmp_path):
    class _BoomLlm:
        def complete_structured(self, **kw):
            raise RuntimeError("provider exploded")

    class _BoomCtx:
        llm = _BoomLlm()

        def register_command(self, name, handler, description, args_hint=""):
            self.handler = handler

    ctx = _BoomCtx()
    plugin.register(ctx)
    _seed_session(monkeypatch, tmp_path)
    out = ctx.handler("deep")
    assert "judge failed" in out.lower()
    assert "deterministic" in out.lower()  # deterministic result still shown


def test_pulse_deep_persists_run_mode(monkeypatch, tmp_path):
    import sqlite3

    from pulse.paths import state_db

    ctx = _FakeCtxWithLlm()
    plugin.register(ctx)
    _seed_session(monkeypatch, tmp_path)
    ctx.handler("deep")
    conn = sqlite3.connect(str(state_db()))
    row = conn.execute("SELECT run_mode FROM pulse_results WHERE session_id='sess-deep-1'").fetchone()
    conn.close()
    assert row[0] == "deep"


def test_pulse_deep_without_host_cost_shows_tokens_only(monkeypatch, tmp_path):
    """No cost_usd from harness -> tokens print, no dollar figure (never estimated)."""

    class _NoCostUsage:
        input_tokens = 120
        output_tokens = 30
        total_tokens = 150
        cost_usd = None

    class _NoCostResult(_FakeLlmResult):
        usage = _NoCostUsage()

    class _NoCostLlm:
        def complete_structured(self, **kw):
            return _NoCostResult()

    class _NoCostCtx:
        llm = _NoCostLlm()

        def register_command(self, name, handler, description, args_hint=""):
            self.handler = handler

    ctx = _NoCostCtx()
    plugin.register(ctx)
    _seed_session(monkeypatch, tmp_path)
    out = ctx.handler("deep")
    assert "150 tokens" in out
    assert "$" not in out
    assert "Hermes reported no dollar cost; tokens are enough" in out
