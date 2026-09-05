"""CLI entry point for hermes-pulse."""
import argparse
import json
from pathlib import Path

from pulse.paths import state_db
from pulse.session_store import load_messages
from pulse.signals import extract_signals


def load_session_from_db(session_id: str | None = None, db_path: Path | None = None) -> list[dict]:
    return load_messages(session_id, db_path)


def render_card(result, task_type: str) -> str:
    user_signals = [s for s in result.signals if s.target == "user"]
    agent_signals = [s for s in result.signals if s.target == "agent"]
    all_signals = user_signals + agent_signals
    total_penalty = sum(s.penalty for s in all_signals)
    status = "GREEN" if total_penalty <= 15 else "YELLOW" if total_penalty <= 30 else "RED"
    m = result.metrics
    lines = ["", "  ╭─ Pulse ─────────────────────────────────────────────╮",
             f"  │  {m['total_turns']:>3} turns  │  ~{m['total_tokens']:,} tokens  │  {m['tool_call_count']:>3} tool calls  │",
             f"  │  Type: {task_type:<12}  Status: {status:<5}             │",
             "  ╰─────────────────────────────────────────────────────╯", ""]
    return "\n".join(lines)


def main() -> None:
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "analyze":
        from pulse.protocol import main as protocol_main
        raise SystemExit(protocol_main())
    parser = argparse.ArgumentParser(description="Hermes Pulse — session health monitor")
    parser.add_argument("--file", "-f", help="Session JSONL file")
    parser.add_argument("--session", "-s", help="Session ID from state.db")
    parser.add_argument("--unroll", help="Unroll trace .py file (safe AST load, never executes)")
    parser.add_argument("--deep", action="store_true", help="Reserved; not implemented")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()
    if args.deep:
        parser.error("--deep is not implemented; use deterministic analysis")
    messages: list[dict] = []
    unroll_meta: dict = {}
    if args.unroll:
        from pulse.unroll_loader import bundle_to_messages, load_unroll_trace

        bundle = load_unroll_trace(args.unroll)
        messages = bundle_to_messages(bundle)
        unroll_meta = {
            "session_id": bundle.session_id,
            "model": bundle.model,
            "provider": bundle.provider,
            "cost_usd": bundle.cost_usd,
            "active_skills": bundle.active_skills,
            "timeline_steps": len(bundle.timeline),
        }
    elif args.file:
        with open(args.file, encoding="utf-8") as f:
            for line in f:
                try:
                    if line.strip(): messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    else:
        messages = load_session_from_db(args.session, state_db())
    if not messages:
        print("No messages found. Provide --file, --session, or run from a Hermes session.")
        raise SystemExit(1)
    result = extract_signals(messages)
    if result.skipped_reason:
        print(f"SKIPPED: {result.skipped_reason} ({len(messages)} msgs, {result.metrics.get('user_turns', 0)} user turns)")
        return
    task_type = result.metrics.get("task_type", "chat")
    if args.json:
        print(json.dumps({"task_type": task_type, "unroll": unroll_meta, "metrics": {k:v for k,v in result.metrics.items() if k not in {"user_texts", "agent_texts"}}, "signals": [{"name":s.name,"target":s.target,"severity":s.severity,"penalty":s.penalty,"label":s.label,"evidence":s.evidence[:2]} for s in result.signals]}, indent=2))
    else:
        print(render_card(result, task_type))

if __name__ == "__main__":
    main()
