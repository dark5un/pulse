"""CLI entry point for hermes-pulse."""
import argparse
import json
import sys
from pathlib import Path

from pulse.signals import extract_signals


def load_session_from_db(session_id: str | None = None) -> list[dict]:
    import sqlite3
    db = Path.home() / ".hermes" / "state.db"
    if not db.exists():
        print(f"State DB not found at {db}", file=sys.stderr)
        return []

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row

    if session_id:
        sid = session_id
    else:
        row = conn.execute(
            "SELECT id FROM sessions ORDER BY last_activity_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return []
        sid = row["id"]

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
    return msgs


def main():
    parser = argparse.ArgumentParser(description="Hermes Pulse — session health monitor")
    parser.add_argument("--file", "-f", help="Session JSONL file")
    parser.add_argument("--session", "-s", help="Session ID from state.db")
    parser.add_argument("--deep", action="store_true", help="Run LLM judge analysis (future)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    messages: list[dict] = []
    if args.file:
        with open(args.file) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    elif args.session:
        messages = load_session_from_db(args.session)
    else:
        messages = load_session_from_db()

    if not messages:
        print("No messages found. Provide --file, --session, or run from a Hermes session.")
        sys.exit(1)

    result = extract_signals(messages)
    task_type = result.metrics.get("task_type", "chat")

    if result.skipped_reason:
        print(f"SKIPPED: {result.skipped_reason} ({len(messages)} msgs, {result.metrics.get('user_turns', 0)} user turns)")
        sys.exit(0)

    if args.json:
        output = {
            "task_type": task_type,
            "metrics": {k: v for k, v in result.metrics.items() if k not in ("user_texts", "agent_texts")},
            "signals": [
                {"name": s.name, "target": s.target, "severity": s.severity,
                 "penalty": s.penalty, "label": s.label, "evidence": s.evidence[:2]}
                for s in result.signals
            ],
        }
        print(json.dumps(output, indent=2))
    else:
        print(render_card(result, task_type))


def render_card(result, task_type: str) -> str:
    """Render a human-readable pulse card for in-session display."""

    user_signals = [s for s in result.signals if s.target == "user"]
    agent_signals = [s for s in result.signals if s.target == "agent"]
    all_signals = user_signals + agent_signals
    # Calculate overall status
    total_penalty = sum(s.penalty for s in all_signals)
    if total_penalty == 0:
        status, status_line = "GREEN", "Session looks productive"
    elif total_penalty <= 15:
        status, status_line = "GREEN", "Minor signals, nothing critical"
    elif total_penalty <= 30:
        status, status_line = "YELLOW", "Some issues detected"
    else:
        status, status_line = "RED", "Significant problems found"

    metrics = result.metrics
    lines = []
    lines.append("")
    lines.append("  ╭─ Pulse ─────────────────────────────────────────────╮")
    lines.append(f"  │  {metrics['total_turns']:>3} turns  │  ~{metrics['total_tokens']:,} tokens  │  {metrics['tool_call_count']:>3} tool calls  │")
    lines.append(f"  │  Type: {task_type:<12}  Status: {status:<5}             │")
    lines.append(f"  │  {status_line:<52}│")

    if all_signals:
        lines.append("  ├─ Signals ────────────────────────────────────────────┤")
        for s in all_signals[:8]:
            side = "YOU" if s.target == "user" else "AGT"
            tag = f"{'▶' if s.penalty > 0 else '✓'}"
            evidence_str = ""
            if s.evidence:
                e = s.evidence[0].replace("\n", " ")
                evidence_str = f"\n  │    {e}"
            lines.append(f"  │  {tag} {side}  {s.label}{evidence_str}")

    if result.signals:
        lines.append("  ├─ Coaching ───────────────────────────────────────────┤")
        coaching_shown = 0
        for s in user_signals[:2]:
            if s.name == "vague_prompts" and coaching_shown < 2:
                lines.append("  │  ▶ Try adding file paths, constraints, or expected format│")
                coaching_shown += 1
            elif s.name == "correction_chain" and coaching_shown < 2:
                lines.append("  │  ▶ Instead of 'no', say: 'use X approach because Y'    │")
                coaching_shown += 1
            elif s.name == "frustration" and coaching_shown < 2:
                lines.append("  │  ▶ Specific direction beats frustration               │")
                coaching_shown += 1
        for s in agent_signals[:2]:
            if s.name == "reasoning_loop" and coaching_shown < 2:
                lines.append("  │  ▶ Tell agent: 'proceed with X, don't reconsider'     │")
                coaching_shown += 1
            elif s.name == "tool_repetition" and coaching_shown < 2:
                lines.append("  │  ▶ Tell agent: 'use cached results, don't re-fetch'    │")
                coaching_shown += 1
            elif s.name == "tool_error" and coaching_shown < 2:
                lines.append("  │  ▶ Agent hit tool errors — suggest a different approach│")
                coaching_shown += 1
            elif s.name == "shallow_read" and coaching_shown < 2:
                lines.append("  │  ▶ Ask agent to 'read the relevant files first'       │")
                coaching_shown += 1
        if coaching_shown == 0:
            lines.append("  │  Keep doing what you're doing — no coaching needed ✓  │")

    lines.append("  ╰─────────────────────────────────────────────────────╯")
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    main()