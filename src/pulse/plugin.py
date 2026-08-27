"""Pulse plugin for Hermes — /pulse slash command.

Analyzes the current session, stores results in state.db,
supports feedback loop, trend tracking, and model comparison.

Subcommands:
  /pulse              Analyze current session
  /pulse trends       Show trends over last 20 sessions
  /pulse models       Compare performance across models
  /pulse useful       Mark last signal as useful
  /pulse not-useful   Mark last signal as not useful
"""

import json
import sqlite3
import sys
import time
from pathlib import Path

pulse_src = Path.home() / "workspace" / "pulse" / "src"
if str(pulse_src) not in sys.path:
    sys.path.insert(0, str(pulse_src))

from pulse.signals import extract_signals
from pulse.weights import apply as apply_weight
from pulse.weights import get_feedback_count, record_feedback
from pulse.weights import load as load_weights
from pulse.weights import save as save_weights

TABLE_DDL = """
CREATE TABLE IF NOT EXISTS pulse_results (
    session_id      TEXT PRIMARY KEY,
    run_at          REAL NOT NULL,
    run_mode        TEXT NOT NULL DEFAULT 'deterministic',
    overall_score   INTEGER NOT NULL,
    status          TEXT NOT NULL,
    user_blame_pct  REAL NOT NULL DEFAULT 0,
    agent_blame_pct REAL NOT NULL DEFAULT 0,
    other_blame_pct REAL NOT NULL DEFAULT 0,
    model           TEXT,
    task_type       TEXT,
    signal_details  TEXT,
    feedback_rating INTEGER,
    outcome_rating  INTEGER,
    created_at      REAL NOT NULL DEFAULT (unixepoch())
);
"""


def _get_db() -> sqlite3.Connection:
    """Open state.db, ensuring the pulse_results table exists."""
    db = Path.home() / ".hermes" / "state.db"
    conn = sqlite3.connect(str(db))
    conn.execute(TABLE_DDL)
    # Migrate: add columns if they don't exist (idempotent)
    for col, col_type in [("model", "TEXT"), ("task_type", "TEXT"), ("outcome_rating", "INTEGER")]:
        try:
            conn.execute(f"ALTER TABLE pulse_results ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
    return conn


def _write_result(conn: sqlite3.Connection, session_id: str, model: str,
                  task_type: str, result, signals_flat: list[dict]):
    """Write a pulse analysis result to state.db."""
    user_penalty = sum(s["penalty"] for s in signals_flat if s["target"] == "user")
    agent_penalty = sum(s["penalty"] for s in signals_flat if s["target"] == "agent")
    total_penalty = user_penalty + agent_penalty

    if total_penalty == 0 or total_penalty <= 15:
        status = "green"
    elif total_penalty <= 30:
        status = "yellow"
    else:
        status = "red"

    total = max(total_penalty, 1)
    user_blame = round(user_penalty / total * 100) if total_penalty > 0 else 0
    agent_blame = round(agent_penalty / total * 100) if total_penalty > 0 else 0
    other_blame = max(0, 100 - user_blame - agent_blame)

    overall = (100 - user_penalty + 100 - agent_penalty) // 2

    conn.execute("""
        INSERT OR REPLACE INTO pulse_results
            (session_id, run_at, run_mode, overall_score, status,
             user_blame_pct, agent_blame_pct, other_blame_pct,
             model, task_type, signal_details, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        session_id, time.time(), "deterministic", overall, status,
        user_blame, agent_blame, other_blame,
        model, task_type, json.dumps(signals_flat), time.time(),
    ))
    conn.commit()


def _load_session(session_id: str | None = None) -> tuple[list[dict], str, str]:
    """Load messages from state.db. Returns (messages, session_id, model_name)."""
    db = Path.home() / ".hermes" / "state.db"
    if not db.exists():
        return [], "", ""

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row

    if session_id:
        sid = session_id
    else:
        row = conn.execute(
            "SELECT id FROM sessions ORDER BY last_activity_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            conn.close()
            return [], "", ""
        sid = row["id"]

    # Get model name
    sess = conn.execute(
        "SELECT model FROM sessions WHERE id=?",
        (sid,)
    ).fetchone()
    model = sess["model"] if sess and sess["model"] else "unknown"

    rows = conn.execute(
        "SELECT role, content, tool_calls, tool_name FROM messages WHERE session_id=? ORDER BY id",
        (sid,)
    ).fetchall()
    conn.close()

    msgs = []
    for r in rows:
        msg = {"role": r["role"], "content": r["content"] or ""}
        tc = r["tool_calls"]
        if tc:
            try:
                msg["tool_calls"] = json.loads(tc)
            except json.JSONDecodeError:
                pass
        tn = r["tool_name"]
        if tn:
            tc_list = msg.get("tool_calls", [])
            if not isinstance(tc_list, list):
                tc_list = []
            tc_list.append({"function": {"name": tn}})
            msg["tool_calls"] = tc_list
        msgs.append(msg)
    return msgs, sid, model


def _shorten_model(name: str) -> str:
    """Shorten a model name for display."""
    for prefix in ["deepseek/", "n0404n0404/"]:
        name = name.replace(prefix, "")
    # Truncate long GGUF names
    if len(name) > 30:
        base = name.split("-GGUF")[0] if "-GGUF" in name else name[:30]
        name = base + "…"
    return name


def _render_card(result, signals_flat: list[dict], task_type: str, model: str) -> str:
    """Render a readable pulse card."""
    user_signals = [s for s in signals_flat if s["target"] == "user"]
    agent_signals = [s for s in signals_flat if s["target"] == "agent"]
    all_signals = user_signals + agent_signals

    total_penalty = sum(s["penalty"] for s in all_signals)
    if total_penalty == 0 or total_penalty <= 15:
        status = "GREEN"
    elif total_penalty <= 30:
        status = "YELLOW"
    else:
        status = "RED"

    metrics = result.metrics
    fb_count = get_feedback_count()
    cal = " (calibrating)" if fb_count < 5 else ""
    model_short = _shorten_model(model)

    lines = []
    lines.append("── Pulse ──────────────────────────────────────")
    lines.append(f"  {metrics['total_turns']} turns  ~{metrics['total_tokens']:,} tok  {metrics['tool_call_count']} tools  {task_type}  [{status}]{cal}")
    lines.append(f"  Model: {model_short}")

    if all_signals:
        lines.append("── Signals ────────────────────────────────────")
        for s in all_signals[:6]:
            side = "you" if s["target"] == "user" else "agt"
            marker = "-" if s["penalty"] > 0 else "ok"
            lines.append(f"  [{marker}] {side}: {s['label']}")
            if s.get("evidence"):
                e = s["evidence"][0].replace("\n", " ")[:100]
                lines.append(f"         {e}")

    if signals_flat:
        lines.append("── Coaching ──────────────────────────────────")
        n = 0
        for s in user_signals[:2]:
            if s["name"] == "vague_prompts" and n < 2:
                lines.append("  Try adding file paths, constraints, or expected format"); n += 1
            elif s["name"] == "correction_chain" and n < 2:
                lines.append("  Instead of 'no', say: 'use X approach because Y'"); n += 1
            elif s["name"] == "frustration" and n < 2:
                lines.append("  Specific direction beats frustration every time"); n += 1
        for s in agent_signals[:2]:
            if s["name"] == "reasoning_loop" and n < 2:
                lines.append("  Tell agent: 'proceed with X, don't reconsider'"); n += 1
            elif s["name"] == "tool_repetition" and n < 2:
                lines.append("  Tell agent: 'use cached results, don't re-fetch'"); n += 1
            elif s["name"] == "tool_error" and n < 2:
                lines.append("  Agent hit tool errors — suggest a different approach"); n += 1
            elif s["name"] == "shallow_read" and n < 2:
                lines.append("  Ask agent to 'read the relevant files first'"); n += 1
        if n == 0:
            lines.append("  Keep doing what you're doing")

    lines.append("── Feedback ───────────────────────────────────")
    lines.append("  Was this accurate? Reply with /pulse useful or /pulse not-useful")
    lines.append("  Did this solve your problem? Reply with /pulse yes or /pulse no")
    lines.append("───────────────────────────────────────────────")
    return "\n".join(lines)


def _handle_trends() -> str:
    """Show trends over last 20 analyzed sessions, grouped by model."""
    conn = _get_db()
    rows = conn.execute("""
        SELECT session_id, run_at, overall_score, status,
               user_blame_pct, agent_blame_pct, model, task_type, signal_details
        FROM pulse_results
        ORDER BY run_at DESC
        LIMIT 20
    """).fetchall()
    conn.close()

    if not rows:
        return "No pulse data yet. Run /pulse on a session first."

    from collections import Counter, defaultdict

    lines = []
    lines.append("── Pulse Trends ───────────────────────────────")
    lines.append(f"  Last {len(rows)} sessions analyzed\n")

    # Overall stats
    avg_score = sum(r["overall_score"] for r in rows) / len(rows)
    green = sum(1 for r in rows if r["status"] == "green")
    yellow = sum(1 for r in rows if r["status"] == "yellow")
    red = sum(1 for r in rows if r["status"] == "red")
    avg_user = sum(r["user_blame_pct"] for r in rows) / len(rows)

    lines.append(f"  Avg score: {avg_score:.0f}/100")
    lines.append(f"  Sessions: {green} green, {yellow} yellow, {red} red")
    lines.append(f"  Avg blame: you {avg_user:.0f}% / agent {100-avg_user:.0f}%")

    # Per-model breakdown
    model_data = defaultdict(list)
    for r in rows:
        m = r["model"] or "unknown"
        model_data[m].append(r)

    if len(model_data) > 1:
        lines.append(f"\n── By Model ────────────────────────────────────")
        for model, mrows in sorted(model_data.items(), key=lambda x: len(x[1]), reverse=True):
            m_short = _shorten_model(model)
            m_avg = sum(r["overall_score"] for r in mrows) / len(mrows)
            m_green = sum(1 for r in mrows if r["status"] == "green")
            m_user = sum(r["user_blame_pct"] for r in mrows) / len(mrows)
            lines.append(f"  {m_short}")
            lines.append(f"    {len(mrows)} sessions  avg {m_avg:.0f}/100  {m_green} green  you {m_user:.0f}% blame")

    # Common signals
    sig_counter = Counter()
    for r in rows:
        if r["signal_details"]:
            try:
                sigs = json.loads(r["signal_details"])
                for s in sigs:
                    if s["penalty"] > 0:
                        sig_counter[s["name"]] += 1
            except (json.JSONDecodeError, KeyError):
                pass

    if sig_counter:
        lines.append("\n  Most common signals:")
        for name, count in sig_counter.most_common(5):
            lines.append(f"    {name}: {count}x")

    lines.append(f"\n  Session details:")
    for r in rows[:10]:
        import datetime
        ts = datetime.datetime.fromtimestamp(r["run_at"], tz=datetime.UTC).strftime("%m-%d %H:%M")
        sid_short = r["session_id"][-12:]
        model_short = _shorten_model(r["model"] or "?")
        lines.append(f"    {ts}  {model_short:20s}  score={r['overall_score']}  [{r['status']}]")

    lines.append("───────────────────────────────────────────────")
    return "\n".join(lines)


def _handle_models() -> str:
    """Compare performance across all models."""
    conn = _get_db()
    rows = conn.execute("""
        SELECT model, task_type, overall_score, status, user_blame_pct, agent_blame_pct
        FROM pulse_results
        WHERE model IS NOT NULL AND model != ''
        ORDER BY run_at DESC
    """).fetchall()
    conn.close()

    if not rows:
        return "No pulse data yet. Run /pulse on a session first."

    from collections import defaultdict

    model_data = defaultdict(list)
    for r in rows:
        model_data[r["model"]].append(r)

    lines = []
    lines.append("── Model Performance ──────────────────────────")
    lines.append(f"  {len(rows)} sessions across {len(model_data)} models\n")

    for model, mrows in sorted(model_data.items(), key=lambda x: len(x[1]), reverse=True):
        m_short = _shorten_model(model)
        m_avg = sum(r["overall_score"] for r in mrows) / len(mrows)
        total = len(mrows)
        green = sum(1 for r in mrows if r["status"] == "green")
        yellow = sum(1 for r in mrows if r["status"] == "yellow")
        red = sum(1 for r in mrows if r["status"] == "red")
        avg_user = sum(r["user_blame_pct"] for r in mrows) / len(mrows)
        avg_agent = sum(r["agent_blame_pct"] for r in mrows) / len(mrows)

        # Task type breakdown
        tasks = defaultdict(int)
        for r in mrows:
            tasks[r["task_type"] or "unknown"] += 1
        task_str = ", ".join(f"{t}: {c}" for t, c in sorted(tasks.items(), key=lambda x: -x[1]))

        lines.append(f"  {m_short}")
        lines.append(f"    {total} sessions  avg {m_avg:.0f}/100  [{green}/{yellow}/{red}]")
        lines.append(f"    Tasks: {task_str}")
        lines.append(f"    Blame: you {avg_user:.0f}%  agent {avg_agent:.0f}%")

    # Best model recommendation (placeholder)
    if len(model_data) >= 2:
        lines.append("\n── Recommendations ────────────────────────────")
        # Find best model per task type
        task_best = defaultdict(list)
        for model, mrows in model_data.items():
            for r in mrows:
                task_best[r["task_type"] or "unknown"].append((r["overall_score"], model))

        for task, scores in sorted(task_best.items()):
            if len(scores) >= 3:
                avg_by_model = defaultdict(list)
                for score, model in scores:
                    avg_by_model[model].append(score)
                best = max(avg_by_model, key=lambda m: sum(avg_by_model[m]) / len(avg_by_model[m]))
                best_score = sum(avg_by_model[best]) / len(avg_by_model[best])
                lines.append(f"  For [{task}] tasks, {_shorten_model(best)} averages {best_score:.0f}/100")
            else:
                lines.append(f"  For [{task}] tasks: need more data (only {len(scores)} sessions)")

        lines.append("\n  (Recommendations improve as more sessions are analyzed)")

    lines.append("───────────────────────────────────────────────")
    return "\n".join(lines)


def _handle_pulse(raw_args: str) -> str:
    """Run pulse analysis and return formatted card with feedback prompt."""
    args = raw_args.strip()

    # Subcommands
    if args in ("trends", "trend"):
        return _handle_trends()

    if args == "models":
        return _handle_models()

    if args == "useful":
        conn = _get_db()
        row = conn.execute(
            "SELECT session_id, signal_details FROM pulse_results ORDER BY run_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            conn.close()
            return "No pulse results to rate. Run /pulse first."
        conn.execute("UPDATE pulse_results SET feedback_rating = 1 WHERE session_id = ?", (row["session_id"],))
        conn.commit()
        conn.close()

        weights = load_weights()
        if row["signal_details"]:
            try:
                sigs = json.loads(row["signal_details"])
                for s in sigs:
                    if s["penalty"] > 0:
                        weights = record_feedback(weights, s["name"], useful=True)
            except (json.JSONDecodeError, KeyError):
                pass
        save_weights(weights)
        return "  Thanks! Weights will adjust over time. (useful)"

    if args == "not-useful" or args == "not useful":
        conn = _get_db()
        row = conn.execute(
            "SELECT session_id, signal_details FROM pulse_results ORDER BY run_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            conn.close()
            return "No pulse results to rate. Run /pulse first."
        conn.execute("UPDATE pulse_results SET feedback_rating = -1 WHERE session_id = ?", (row["session_id"],))
        conn.commit()
        conn.close()

        weights = load_weights()
        if row["signal_details"]:
            try:
                sigs = json.loads(row["signal_details"])
                for s in sigs:
                    if s["penalty"] > 0:
                        weights = record_feedback(weights, s["name"], useful=False)
            except (json.JSONDecodeError, KeyError):
                pass
        save_weights(weights)
        return "  Thanks! Weights will adjust over time. (not useful)"

    if args in ("yes", "y"):
        conn = _get_db()
        conn.execute(
            "UPDATE pulse_results SET outcome_rating = 1 WHERE session_id = (SELECT session_id FROM pulse_results ORDER BY run_at DESC LIMIT 1)"
        )
        conn.commit()
        conn.close()
        return "  Great! Outcome recorded as resolved."

    if args in ("no", "n"):
        conn = _get_db()
        conn.execute(
            "UPDATE pulse_results SET outcome_rating = 0 WHERE session_id = (SELECT session_id FROM pulse_results ORDER BY run_at DESC LIMIT 1)"
        )
        conn.commit()
        conn.close()
        return "  Noted. Outcome recorded as unresolved."

    # Main pulse analysis
    session_id = args if args and not args.startswith("--") else None
    messages, sid, model = _load_session(session_id)

    if not messages:
        return "No messages found. Try /pulse from an active session."

    # Apply learned weights to signals
    weights = load_weights()
    result = extract_signals(messages)
    task_type = result.metrics.get("task_type", "chat")

    if result.skipped_reason:
        n = len(messages)
        u = result.metrics.get("user_turns", 0)
        return f"Session too short to analyze ({n} msgs, {u} user turns): {result.skipped_reason}"

    # Flatten signals with applied weights
    signals_flat = []
    for s in result.signals:
        adjusted = apply_weight(weights, s.name, s.penalty)
        signals_flat.append({
            "name": s.name,
            "target": s.target,
            "severity": s.severity,
            "penalty": adjusted,
            "label": s.label,
            "evidence": s.evidence[:2] if s.evidence else [],
        })

    # Persist to state.db
    conn = _get_db()
    _write_result(conn, sid, model, task_type, result, signals_flat)
    conn.close()

    return _render_card(result, signals_flat, task_type, model)


def register(ctx):
    """Register the /pulse slash command."""
    _get_db().close()

    ctx.register_command(
        "pulse",
        handler=_handle_pulse,
        description="Analyze session quality. Subcommands: trends, models, useful, not-useful, yes, no",
        args_hint="[trends|models|useful|not-useful|yes|no]",
    )