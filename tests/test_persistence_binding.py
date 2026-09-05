"""WU-3 (PU-4, PU-5, PU-8, PU-9): persistence and session binding.

- deep-mode: LLM lane missing -> exactly one row run_mode=deep_unavailable;
  judge raising -> one row deep_failed; success -> one row deep_success.
  No path produces zero rows.
- feedback isolation: results for sessions A then B; feedback bound to A
  changes only A's row. No interactive feedback path issues a global
  ORDER BY run_at DESC LIMIT 1.
- load_session against valid-SQLite-but-wrong-schema -> typed
  SchemaIncompatibleError, distinct from missing/empty DB.
- malformed JSONL -> non-zero exit with line numbers and a count;
  --best-effort opts into skipping, malformed counts in --json.
"""

import json
import sqlite3
import time


def _seed_hermes_session(monkeypatch, sid, n_turns=3):
    import sqlite3

    from pulse.paths import state_db

    db = state_db()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, model TEXT, last_activity_at REAL)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, "
        "content TEXT, tool_calls TEXT, tool_name TEXT)"
    )
    msgs = []
    for i in range(n_turns):
        msgs.append(("user", f"user question {i} about python code please"))
        msgs.append(("assistant", f"assistant answer {i} with enough detail here"))
    msgs.append(("user", "thanks, that solves it"))
    conn.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?, ?)", (sid, "m", time.time()))
    conn.executemany(
        "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
        [(sid, role, content) for role, content in msgs],
    )
    conn.commit()
    conn.close()


class _FakeUsage:
    input_tokens = 120
    output_tokens = 30
    total_tokens = 150
    cost_usd = 0.001


class _FakeLlmResult:
    text = json.dumps({"prompt_version": "v1", "verdicts": [
        {"signal": "goal_completion", "finding": "yes", "penalty": 0, "evidence": "task done"},
    ]})
    provider = "openrouter"
    model = "meta/muse-spark-1.3"
    usage = _FakeUsage()


class _FakeLlm:
    def complete_structured(self, **kw):
        return _FakeLlmResult()


class _Ctx:
    def __init__(self, llm=None):
        self.llm = llm

    def register_command(self, name, handler, description, args_hint=""):
        self.handler = handler


def _run_modes(sid):
    from pulse.paths import state_db

    conn = sqlite3.connect(str(state_db()))
    rows = conn.execute("SELECT run_mode FROM pulse_results WHERE session_id=?", (sid,)).fetchall()
    conn.close()
    return [r[0] for r in rows]


def test_deep_unavailable_persists_one_row(monkeypatch):
    from pulse import plugin as plugin_module

    _seed_hermes_session(monkeypatch, "sess-w3-a")
    ctx = _Ctx(llm=None)
    plugin_module.register(ctx)
    out = ctx.handler("deep")
    assert "not available" in out.lower()
    assert _run_modes("sess-w3-a") == ["deep_unavailable"]


def test_deep_failed_persists_one_row(monkeypatch):
    from pulse import plugin as plugin_module

    class _Boom:
        def complete_structured(self, **kw):
            raise RuntimeError("provider exploded")

    _seed_hermes_session(monkeypatch, "sess-w3-b")
    ctx = _Ctx(llm=_Boom())
    plugin_module.register(ctx)
    out = ctx.handler("deep")
    assert "judge failed" in out.lower()
    assert _run_modes("sess-w3-b") == ["deep_failed"]


def test_deep_success_persists_one_row(monkeypatch):
    from pulse import plugin as plugin_module

    _seed_hermes_session(monkeypatch, "sess-w3-c")
    ctx = _Ctx(llm=_FakeLlm())
    plugin_module.register(ctx)
    ctx.handler("deep")
    assert _run_modes("sess-w3-c") == ["deep_success"]


def test_feedback_binds_to_current_session_not_global_latest(monkeypatch):
    from pulse import plugin as plugin_module

    _seed_hermes_session(monkeypatch, "sess-A")
    _seed_hermes_session(monkeypatch, "sess-B")
    ctx = _Ctx(llm=_FakeLlm())
    plugin_module.register(ctx)
    ctx.handler("")  # analyzes latest (B)
    ctx.handler("sess-A")  # analyze A; current session is now A
    out = ctx.handler("useful")
    assert "thanks" in out.lower()
    from pulse.paths import state_db

    conn = sqlite3.connect(str(state_db()))
    a = conn.execute("SELECT feedback_rating FROM pulse_results WHERE session_id='sess-A'").fetchone()
    b = conn.execute("SELECT feedback_rating FROM pulse_results WHERE session_id='sess-B'").fetchone()
    conn.close()
    assert a[0] == 1
    assert b[0] is None


def test_feedback_with_no_analysis_for_session(monkeypatch):
    from pulse import plugin as plugin_module

    ctx = _Ctx(llm=_FakeLlm())
    plugin_module.register(ctx)
    out = ctx.handler("useful")
    assert "no pulse analysis for this session" in out.lower()


def test_yes_no_bind_to_current_session(monkeypatch):
    from pulse import plugin as plugin_module

    _seed_hermes_session(monkeypatch, "sess-Y")
    _seed_hermes_session(monkeypatch, "sess-Z")
    ctx = _Ctx(llm=_FakeLlm())
    plugin_module.register(ctx)
    ctx.handler("")  # analyzes latest (Z)
    ctx.handler("sess-Y")  # analyze Y; current session is now Y
    ctx.handler("yes")
    from pulse.paths import state_db

    conn = sqlite3.connect(str(state_db()))
    y = conn.execute("SELECT outcome_rating FROM pulse_results WHERE session_id='sess-Y'").fetchone()
    z = conn.execute("SELECT outcome_rating FROM pulse_results WHERE session_id='sess-Z'").fetchone()
    conn.close()
    assert y[0] == 1
    assert z[0] is None


def test_no_global_order_by_in_feedback_paths():
    import inspect

    from pulse import plugin as plugin_module

    for name in ("useful", "yes", "no"):
        pass
    src = inspect.getsource(plugin_module._handle_pulse)
    assert "ORDER BY run_at DESC LIMIT 1" not in src


def test_load_session_wrong_schema_raises_typed_error(tmp_path):
    from pulse.session_store import SchemaIncompatibleError, load_session

    db = tmp_path / "odd.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE things (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    try:
        load_session("whatever", db_path=db)
    except SchemaIncompatibleError as e:
        assert "session database" in str(e).lower()
    else:
        raise AssertionError("wrong-schema DB did not raise")


def test_load_session_missing_db_returns_empty(tmp_path):
    from pulse.session_store import load_session

    msgs, sid, model = load_session("nope", db_path=tmp_path / "missing.db")
    assert (msgs, sid, model) == ([], "", "")


def test_jsonl_malformed_exits_nonzero_with_counts(tmp_path, capsys):
    import sys

    from pulse.__main__ import main

    f = tmp_path / "s.jsonl"
    f.write_text(
        '{"role": "user", "content": "hello world today please"}\n'
        "NOT JSON AT ALL\n"
        '{"role": "assistant", "content": "hi there friend, all good today"}\n'
        "{broken\n"
    )
    old_argv = sys.argv
    try:
        sys.argv = ["pulse", "--file", str(f)]
        try:
            main()
        except SystemExit as e:
            assert e.code == 1
        else:
            raise AssertionError("malformed JSONL exited 0")
    finally:
        sys.argv = old_argv
    out = capsys.readouterr().out
    assert "line 2" in out and "line 4" in out


def test_jsonl_best_effort_skips_and_reports(tmp_path, capsys):
    import sys

    from pulse.__main__ import main

    f = tmp_path / "s.jsonl"
    f.write_text(
        '{"role": "user", "content": "hello world today please"}\n'
        "NOT JSON\n"
        '{"role": "assistant", "content": "hi there friend, all good today"}\n'
    )
    old_argv = sys.argv
    try:
        sys.argv = ["pulse", "--file", str(f), "--best-effort"]
        main()
    finally:
        sys.argv = old_argv
    out = capsys.readouterr().out
    assert "skipped" in out.lower() or "malformed" in out.lower()
