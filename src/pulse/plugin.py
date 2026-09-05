"""Pulse plugin for Hermes — /pulse slash command.

Analyzes the current session, stores results in state.db,
supports feedback loop, trend tracking, model comparison, and
opt-in LLM-judge deep analysis (``/pulse deep`` — one extra model call,
billed to the active model).

Subcommands:
  /pulse              Analyze current session
  /pulse deep         Deterministic analysis + LLM judge (costs tokens!)
  /pulse trends       Show trends over last 20 sessions
  /pulse models       Compare performance across models
  /pulse useful       Mark last signal as useful
  /pulse not-useful   Mark last signal as not useful
"""

import json
import sqlite3
import time
from pathlib import Path

# NOTE: no sys.path manipulation here. The Hermes directory loader imports
# this file as a real package (hermes_plugins.pulse, __path__ = plugin dir),
# so sibling modules resolve via relative import. Absolute `pulse.*` imports
# below would resolve against cwd — keep everything relative.
from .paths import state_db
from .scoring import score_penalties
from .session_store import load_session
from .signals import extract_signals
from .weights import apply as apply_weight
from .weights import get_feedback_count, record_feedback
from .weights import load as load_weights
from .weights import save as save_weights

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


def _get_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Open state.db, ensuring the pulse_results table exists."""
    db = db_path or state_db()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.execute(TABLE_DDL)
    # Migrate: add columns if they don't exist (idempotent)
    for col, col_type in [("model", "TEXT"), ("task_type", "TEXT"), ("outcome_rating", "INTEGER")]:
        try:
            conn.execute(f"ALTER TABLE pulse_results ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                conn.close()
                raise
    conn.commit()
    return conn


def _write_result(conn: sqlite3.Connection, session_id: str, model: str,
                  task_type: str, result, signals_flat: list[dict],
                  run_mode: str = "deterministic"):
    """Write a pulse analysis result to state.db."""
    user_penalty = sum(s["penalty"] for s in signals_flat if s["target"] == "user")
    agent_penalty = sum(s["penalty"] for s in signals_flat if s["target"] == "agent")
    other_penalty = sum(s["penalty"] for s in signals_flat if s["target"] not in {"user", "agent"})
    breakdown = score_penalties({"user": user_penalty, "agent": agent_penalty, "other": other_penalty})

    conn.execute("""
        INSERT INTO pulse_results
            (session_id, run_at, run_mode, overall_score, status,
             user_blame_pct, agent_blame_pct, other_blame_pct,
             model, task_type, signal_details, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET run_at=excluded.run_at, run_mode=excluded.run_mode, overall_score=excluded.overall_score, status=excluded.status, user_blame_pct=excluded.user_blame_pct, agent_blame_pct=excluded.agent_blame_pct, other_blame_pct=excluded.other_blame_pct, model=excluded.model, task_type=excluded.task_type, signal_details=excluded.signal_details
    """, (
        session_id, time.time(), run_mode, breakdown.score, breakdown.status,
        breakdown.attribution["user"], breakdown.attribution["agent"], breakdown.attribution["other"],
        model, task_type, json.dumps(signals_flat), time.time(),
    ))
    conn.commit()


def _load_session(session_id: str | None = None) -> tuple[list[dict], str, str]:
    """Load through the shared defensive session store."""
    from .session_store import SchemaIncompatibleError

    try:
        return load_session(session_id)
    except SchemaIncompatibleError:
        return [], "", ""

def _shorten_model(name: str) -> str:
    """Shorten a model name for display."""
    for prefix in ["deepseek/", "n0404n0404/"]:
        name = name.replace(prefix, "")
    # Truncate long GGUF names
    if len(name) > 30:
        base = name.split("-GGUF")[0] if "-GGUF" in name else name[:30]
        name = base + "…"
    return name


def _render_card(result, signals_flat: list[dict], task_type: str, model: str, runtime_logs: list | None = None) -> str:
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
                e = s["evidence"][0].replace("\n", " ")
                lines.append(f"         {e}")

    # Runtime log section — shows tool errors without penalising score
    if runtime_logs:
        lines.append("── Runtime Log ──────────────────────────────")
        for log in runtime_logs[:6]:
            lines.append(f"  [{log['module']}] {log['error']}")

    if signals_flat:
        lines.append("── Coaching ──────────────────────────────────")
        shown = set()
        for s in user_signals[:2]:
            if s["name"] == "vague_prompts" and "vague" not in shown:
                lines.append("  Try adding file paths, constraints, or expected format"); shown.add("vague")
            elif s["name"] == "correction_chain" and "chain" not in shown:
                lines.append("  Instead of 'no', say: 'use X approach because Y'"); shown.add("chain")
            elif s["name"] == "frustration" and "frustration" not in shown:
                lines.append("  Specific direction beats frustration every time"); shown.add("frustration")
        for s in agent_signals[:3]:
            if s["name"] == "reasoning_loop" and "loop" not in shown:
                lines.append("  Tell agent: 'proceed with X, don't reconsider'"); shown.add("loop")
            elif s["name"] == "tool_repetition" and "repetition" not in shown:
                lines.append("  Tell agent: 'use cached results, don't re-fetch'"); shown.add("repetition")
            elif s["name"] == "shallow_read" and "readdepth" not in shown:
                lines.append("  Ask agent to 'read the relevant files first'"); shown.add("readdepth")
        if not shown:
            lines.append("  Keep doing what you're doing")

    lines.append("── Feedback ───────────────────────────────────")
    lines.append("  Was this accurate? Reply with /pulse useful or /pulse not-useful")
    lines.append("  Did this solve your problem? Reply with /pulse yes or /pulse no")
    lines.append("───────────────────────────────────────────────")
    return "\n".join(lines)


def _serialise_runtime_logs(result) -> list[dict]:
    """Serialise RuntimeLog objects to dicts for persistence."""
    return [
        {"module": log.module, "error": log.error, "severity": log.severity or "info"}
        for log in (result.runtime_logs or [])
    ]


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
        lines.append("\n── By Model ────────────────────────────────────")
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

    lines.append("\n  Session details:")
    for r in rows[:10]:
        import datetime
        ts = datetime.datetime.fromtimestamp(r["run_at"], tz=datetime.UTC).strftime("%m-%d %H:%M")
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


_LLM_CTX = None  # stashed PluginContext — slash handlers receive only raw_args

#: Session id of the most recently analyzed session in this process.
#: All feedback verbs bind to it — never to a global latest row.
_CURRENT_SESSION_ID: str | None = None


def _set_current_session(session_id: str) -> None:
    global _CURRENT_SESSION_ID
    _CURRENT_SESSION_ID = session_id


def _feedback_target(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Resolve the feedback target: current session's row, else None."""
    if _CURRENT_SESSION_ID is None:
        return None
    return conn.execute(
        "SELECT session_id, signal_details, feedback_rating FROM pulse_results WHERE session_id = ?",
        (_CURRENT_SESSION_ID,),
    ).fetchone()


def _handle_deep() -> str:
    """Deterministic analysis + one host-owned LLM-judge call (costs tokens!).

    Runs on the user's ACTIVE model via ctx.llm — no key setup, billed to
    whatever Hermes is using. Judge failure is loud (error string + the
    deterministic card), never a silent fallback.
    """
    import time

    from .signals_deep import build_prompt, parse_verdict_text

    t0 = time.time()
    messages, sid, model = _load_session(None)
    if not messages:
        return "No messages found. Try /pulse deep from an active session."
    weights = load_weights()
    result = extract_signals(messages)
    task_type = result.metrics.get("task_type", "chat")
    if result.skipped_reason:
        n = len(messages)
        u = result.metrics.get("user_turns", 0)
        return f"Session too short to analyze ({n} msgs, {u} user turns): {result.skipped_reason}"
    signals_flat = []
    for s in result.signals:
        adjusted = apply_weight(weights, s.name, s.penalty)
        signals_flat.append({
            "name": s.name, "target": s.target, "severity": s.severity,
            "penalty": adjusted, "label": s.label,
            "evidence": s.evidence[:2] if s.evidence else [],
        })
    runtime_logs_serialised = _serialise_runtime_logs(result)
    llm = getattr(_LLM_CTX, "llm", None) if _LLM_CTX is not None else None
    if llm is None:
        conn = _get_db()
        _write_result(conn, sid, model, task_type, result, signals_flat, run_mode="deep_unavailable")
        conn.close()
        _set_current_session(sid)
        card = _render_card(result, signals_flat, task_type, model,
                            runtime_logs=runtime_logs_serialised)
        return card + (
            "\n── Judge ──────────────────────────────────────\n"
            "  Deep analysis not available: host LLM lane missing.\n"
            "  Deterministic result above.\n"
            "───────────────────────────────────────────────"
        )
    prompt = build_prompt(messages)
    try:
        res = llm.complete_structured(
            instructions="You are Pulse, a session-quality judge. Reply with exactly the requested JSON shape.",
            input=[{"type": "text", "text": prompt}],
            json_mode=True, temperature=0.0, max_tokens=800, timeout=120,
            purpose="pulse-deep-judge",
        )
    except Exception as e:  # noqa: BLE001 — judge failure must surface, never swallow
        conn = _get_db()
        _write_result(conn, sid, model, task_type, result, signals_flat, run_mode="deep_failed")
        conn.close()
        _set_current_session(sid)
        card = _render_card(result, signals_flat, task_type, model,
                            runtime_logs=runtime_logs_serialised)
        return card + (
            "\n── Judge ──────────────────────────────────────\n"
            f"  Judge failed: {e}.\n"
            "  Deterministic result above still stands.\n"
            "───────────────────────────────────────────────"
        )
    deep_result = parse_verdict_text(res.text)
    deep_signals = deep_result.signals
    for s in deep_signals:
        adjusted = apply_weight(weights, s.name, s.penalty)
        signals_flat.append({
            "name": s.name, "target": s.target, "severity": s.severity,
            "penalty": adjusted, "label": s.label,
            "evidence": s.evidence[:2] if s.evidence else [],
        })
    usage = getattr(res, "usage", None)
    in_tok = getattr(usage, "input_tokens", 0) or 0
    out_tok = getattr(usage, "output_tokens", 0) or 0
    total = (getattr(usage, "total_tokens", 0) or 0) or (in_tok + out_tok)
    # Cost: dollars from Hermes alone when it reports them;
    # otherwise tokens are enough — never estimated, never fabricated.
    cost = getattr(usage, "cost_usd", None)
    if cost is not None:
        cost_label = f", ~${cost:.4f} (cost from Hermes)"
    else:
        cost_label = " (Hermes reported no dollar cost; tokens are enough)"
    elapsed = time.time() - t0
    conn = _get_db()
    _write_result(conn, sid, model, task_type, result, signals_flat, run_mode="deep_success")
    conn.close()
    _set_current_session(sid)
    card = _render_card(result, signals_flat, task_type, model,
                        runtime_logs=runtime_logs_serialised)
    judge_lines = [
        "── Judge ──────────────────────────────────────",
        f"  Model: {getattr(res, 'model', '?')} ({getattr(res, 'provider', '?')})",
        f"  Verdicts: {', '.join(s.name for s in deep_signals) or 'no findings'}",
        f"  Cost: {total} tokens ({in_tok} in / {out_tok} out)"
        + cost_label
        + f", {elapsed:.0f}s — billed to your active model",
        "  Provisional until agreement-gated (kappa>=0.6, n>=50).",
        "───────────────────────────────────────────────",
    ]
    return card + "\n" + "\n".join(judge_lines)


def _handle_pulse(raw_args: str) -> str:
    """Run pulse analysis and return formatted card with feedback prompt."""
    args = raw_args.strip()

    # Subcommands
    if args == "deep":
        return _handle_deep()
    if args in ("trends", "trend"):
        return _handle_trends()

    if args == "models":
        return _handle_models()

    if args in {"useful", "not-useful", "not useful"}:
        useful = args == "useful"
        conn = _get_db()
        row = _feedback_target(conn)
        if not row:
            conn.close()
            return "No pulse analysis for this session yet. Run /pulse first, then rate it."
        if row["feedback_rating"] is not None:
            conn.close()
            return "This pulse result is already rated; feedback was not counted again."
        conn.execute("UPDATE pulse_results SET feedback_rating = ? WHERE session_id = ?", (1 if useful else -1, row["session_id"]))
        conn.commit(); conn.close()

        weights = load_weights()
        if row["signal_details"]:
            try:
                sigs = json.loads(row["signal_details"])
                for signal in sigs:
                    if isinstance(signal, dict) and signal.get("penalty", 0) > 0:
                        weights = record_feedback(weights, signal.get("name", ""), useful)
            except (json.JSONDecodeError, TypeError):
                pass
        save_weights(weights)
        return "  Thanks! Weights will adjust over time. (useful)" if useful else "  Thanks! Weights will adjust over time. (not useful)"

    if args in ("yes", "y"):
        conn = _get_db()
        row = _feedback_target(conn)
        if not row:
            conn.close()
            return "No pulse analysis for this session yet. Run /pulse first."
        conn.execute(
            "UPDATE pulse_results SET outcome_rating = 1 WHERE session_id = ?",
            (row["session_id"],),
        )
        conn.commit()
        conn.close()
        return "  Great! Outcome recorded as resolved."

    if args in ("no", "n"):
        conn = _get_db()
        row = _feedback_target(conn)
        if not row:
            conn.close()
            return "No pulse analysis for this session yet. Run /pulse first."
        conn.execute(
            "UPDATE pulse_results SET outcome_rating = 0 WHERE session_id = ?",
            (row["session_id"],),
        )
        conn.commit()
        conn.close()
        return "  Noted. Outcome recorded as unresolved."

    # Main pulse analysis; slash commands never reinterpret unsupported flags.
    if args.startswith("-") or (args and args not in {"trends", "trend", "models"} and " " in args):
        return "Unsupported /pulse option. Supported: deep, trends, models, useful, not-useful, yes, no, or a session ID."
    session_id = args or None
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

    # Serialise runtime logs for persistence
    runtime_logs_serialised = _serialise_runtime_logs(result)

    # Persist to state.db
    conn = _get_db()
    _write_result(conn, sid, model, task_type, result, signals_flat)
    conn.close()
    _set_current_session(sid)

    return _render_card(result, signals_flat, task_type, model, runtime_logs=runtime_logs_serialised)


def register(ctx):
    """Register the /pulse slash command."""
    global _LLM_CTX
    _LLM_CTX = ctx
    _get_db().close()

    ctx.register_command(
        "pulse",
        handler=_handle_pulse,
        description="Analyze session quality. Subcommands: deep, trends, models, useful, not-useful, yes, no",
        args_hint="[deep|trends|models|useful|not-useful|yes|no]",
    )