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
        print(f"Task type: {task_type}")
        print(f"Signals: {len(result.signals)}")
        for s in result.signals:
            penalty = f" -{s.penalty}" if s.penalty > 0 else ""
            print(f"  [{s.target.upper():5s}] {s.name}{penalty}")
            for e in s.evidence[:1]:
                print(f"         \"{e[:80]}\"")
        print(f"Metrics: {result.metrics['total_turns']} turns, {result.metrics['total_tokens']} tok est, "
              f"Read:Edit={result.metrics['read_edit_ratio']}, "
              f"{result.metrics['tool_call_count']} tool calls")


if __name__ == "__main__":
    main()