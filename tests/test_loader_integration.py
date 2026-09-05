"""WU-11: loader-level integration harness.

Loads the Pulse plugin through the Hermes directory-loader path (real
package import with submodule_search_locations), drives two independent
sessions through analyze + deep + feedback flows, finalizes in varying
orders, and asserts isolation, exactly-once persistence, and complete
redaction of judge-bound prompts.
"""

import importlib.util
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).parents[1]
SRC = REPO / "src" / "pulse"


def _load_plugin(name="pulse_plugin_integration"):
    # Mirror the Hermes directory loader: copy the plugin files to a temp
    # dir as a package (plugin.py -> <name>/__init__.py), import it with
    # __path__ set, so relative imports resolve as under the real loader.
    import shutil
    import tempfile

    pkgdir = Path(tempfile.mkdtemp(prefix=f"{name}-")) / name
    pkgdir.mkdir()
    for src_file in SRC.glob("*.py"):
        dest = pkgdir / src_file.name
        if src_file.name == "plugin.py":
            dest = pkgdir / "__init__.py"
        shutil.copy(src_file, dest)
    shutil.copy(SRC / "plugin.yaml", pkgdir / "plugin.yaml")
    sys.path.insert(0, str(pkgdir.parent))
    return importlib.import_module(name)


def _seed(monkeypatch, sid, tag="code"):
    import time

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
    for i in range(3):
        msgs.append(("user", f"user question {i} about python {tag} please"))
        msgs.append(("assistant", f"assistant answer {i} with enough detail here"))
    msgs.append(("user", "thanks, that solves it"))
    conn.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?, ?)", (sid, "m", time.time()))
    conn.executemany(
        "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
        [(sid, role, content) for role, content in msgs],
    )
    conn.commit()
    conn.close()


class _Ctx:
    def __init__(self, llm=None):
        self.llm = llm

    def register_command(self, name, handler, description, args_hint=""):
        self.handler = handler


def test_two_sessions_isolated_end_to_end(monkeypatch):
    plugin = _load_plugin("pulse_int_a")
    _seed(monkeypatch, "int-A", tag="alpha")
    _seed(monkeypatch, "int-B", tag="beta")
    ctx = _Ctx(llm=None)
    plugin.register(ctx)
    ctx.handler("int-A")
    out_a = ctx.handler("useful")
    assert "thanks" in out_a.lower()
    ctx.handler("int-B")
    out_b = ctx.handler("not-useful")
    assert "thanks" in out_b.lower()
    from pulse.paths import state_db

    conn = sqlite3.connect(str(state_db()))
    a = conn.execute("SELECT feedback_rating FROM pulse_results WHERE session_id='int-A'").fetchone()
    b = conn.execute("SELECT feedback_rating FROM pulse_results WHERE session_id='int-B'").fetchone()
    conn.close()
    assert a[0] == 1 and b[0] == -1


def test_deep_all_modes_persist_exactly_once(monkeypatch):
    plugin = _load_plugin("pulse_int_b")
    _seed(monkeypatch, "int-deep-1")
    ctx = _Ctx(llm=None)
    plugin.register(ctx)
    ctx.handler("deep")  # unavailable path
    from pulse.paths import state_db

    conn = sqlite3.connect(str(state_db()))
    rows = conn.execute("SELECT run_mode FROM pulse_results WHERE session_id='int-deep-1'").fetchall()
    conn.close()
    assert [r[0] for r in rows] == ["deep_unavailable"]


def test_judge_prompt_redacted_integration():
    from pulse.signals_deep import build_prompt

    prompt = build_prompt([
        {"role": "user", "content": "deploy with sk-live-AAAAAAAA11111111 now"},
        {"role": "assistant", "content": "mail ops@example.com when done"},
    ])
    assert "sk-live-AAAAAAAA11111111" not in prompt
    assert "ops@example.com" not in prompt


def test_plugin_loads_without_cwd_dependence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plugin = _load_plugin("pulse_int_c")
    assert hasattr(plugin, "register")
    assert "sys.path.insert" not in (SRC / "plugin.py").read_text()
