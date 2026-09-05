"""CLI entry point for hermes-pulse."""
import argparse
import json
from pathlib import Path

from pulse.judge import JUDGE_MODEL_DEFAULT, OpenAIJudge
from pulse.paths import state_db
from pulse.session_store import load_messages
from pulse.signals import extract_signals


def load_session_from_db(session_id: str | None = None, db_path: Path | None = None) -> list[dict]:
    return load_messages(session_id, db_path)


def render_card(result, task_type: str, unroll_meta: dict | None = None) -> str:
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
    if unroll_meta:
        lines.insert(5, f"  trace {unroll_meta.get('session_id', '?')} · {unroll_meta.get('timeline_steps', 0)} steps · ${unroll_meta.get('cost_usd', 0.0):.4f}")
    for s in all_signals:
        ev = f" — {s.evidence[0][:80]}" if s.evidence else ""
        lines.append(f"  [{s.severity}] {s.name}: {s.label}{ev}")
    return "\n".join(lines)


def main() -> None:
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "analyze":
        from pulse.protocol import main as protocol_main
        raise SystemExit(protocol_main())
    if len(sys.argv) > 1 and sys.argv[1] == "leaderboard":
        from pulse.leaderboard_cli import main as leaderboard_main
        raise SystemExit(leaderboard_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "replay":
        from pulse.replay_cli import main as replay_main
        raise SystemExit(replay_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "compare":
        from pulse.compare_cli import main as compare_main
        raise SystemExit(compare_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "skills":
        from pulse.skills_cli import main as skills_main
        raise SystemExit(skills_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "export":
        from pulse.export_cli import main as export_main
        raise SystemExit(export_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "experiment":
        from pulse.experiment_cli import main as experiment_main
        raise SystemExit(experiment_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "bundle":
        from pulse.artifact_cli import main as bundle_main
        raise SystemExit(bundle_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        from pulse.artifact_cli import verify_main
        raise SystemExit(verify_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "incident":
        from pulse.incident_cli import main as incident_main
        raise SystemExit(incident_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "flake":
        from pulse.incident_cli import flake_main
        raise SystemExit(flake_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "costs":
        from pulse.costs_cli import main as costs_main
        raise SystemExit(costs_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "portability":
        from pulse.portability_cli import main as portability_main
        raise SystemExit(portability_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "agreement":
        from pulse.agreement_cli import main as agreement_main
        raise SystemExit(agreement_main(sys.argv[2:]))
    parser = argparse.ArgumentParser(description="Hermes Pulse — session health monitor")
    parser.add_argument("--file", "-f", help="Session JSONL file")
    parser.add_argument("--session", "-s", help="Session ID from state.db")
    parser.add_argument("--unroll", help="Unroll trace .py file (safe AST load, never executes)")
    parser.add_argument("--deep", action="store_true", help="Add LLM-judge analysis (B2; needs PULSE_API_KEY/OPENAI_API_KEY)")
    parser.add_argument("--judge-model", default="", help="Judge model (default: PULSE_JUDGE_MODEL or gpt-4o-mini)")
    parser.add_argument("--judge-base-url", default="", help="Judge API base URL (default: PULSE_JUDGE_BASE_URL)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()
    messages: list[dict] = []
    unroll_meta: dict = {}
    bundle = None
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
    unroll_signals: list = []
    if args.unroll and bundle is not None:
        from pulse.signals_unroll import (
            detect_cost,
            detect_latency,
            detect_skill_deadweight,
        )

        unroll_signals = (
            detect_latency(bundle)
            + detect_cost(bundle, result.metrics.get("task_type", "coding"))
            + detect_skill_deadweight(bundle, messages)
        )
        result.signals.extend(unroll_signals)
    deep_info: dict | None = None
    if args.deep:
        from pulse.signals_deep import detect_deep

        backend = OpenAIJudge(model=args.judge_model or JUDGE_MODEL_DEFAULT, base_url=args.judge_base_url)
        try:
            deep_signals = detect_deep(messages, backend)
        except SystemExit:
            raise
        except Exception as e:
            print(f"deep judge failed: {e}")
            raise SystemExit(1) from e
        result.signals.extend(deep_signals)
        jr = backend.last_result
        deep_info = {
            "model": getattr(backend, "model", JUDGE_MODEL_DEFAULT),
            "signals": [s.name for s in deep_signals],
            "input_tokens": jr.input_tokens if jr else 0,
            "output_tokens": jr.output_tokens if jr else 0,
        }
    if result.skipped_reason and not unroll_signals:
        print(f"SKIPPED: {result.skipped_reason} ({len(messages)} msgs, {result.metrics.get('user_turns', 0)} user turns)")
        return
    task_type = result.metrics.get("task_type", "chat")
    if args.json:
        payload: dict = {"task_type": task_type, "unroll": unroll_meta, "metrics": {k:v for k,v in result.metrics.items() if k not in {"user_texts", "agent_texts"}}, "signals": [{"name":s.name,"target":s.target,"severity":s.severity,"penalty":s.penalty,"label":s.label,"evidence":s.evidence[:2]} for s in result.signals]}
        if deep_info is not None:
            payload["deep"] = deep_info
        print(json.dumps(payload, indent=2))
    else:
        if deep_info is not None:
            print(f"  deep judge {deep_info['model']}: {', '.join(deep_info['signals']) or 'no findings'} "
                  f"({deep_info['input_tokens']} in / {deep_info['output_tokens']} out tokens)")
        print(render_card(result, task_type, unroll_meta or None))

if __name__ == "__main__":
    main()
