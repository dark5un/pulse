"""`pulse costs` implementation: join-side cost attribution over a corpus."""

from __future__ import annotations

import argparse
import json

from pulse.costs import load_mapping, rollup
from pulse.leaderboard_cli import load_corpus_records


def render_table(groups: dict[str, dict]) -> str:
    if not groups:
        return "No cost data found."
    lines = [f"{'team':<20} {'sessions':>8} {'total_usd':>10}  by_task"]
    for team in sorted(groups, key=lambda t: -groups[t]["total_usd"]):
        g = groups[team]
        tasks = ",".join(f"{t}:{v:.4f}" for t, v in sorted(g["by_task"].items()))
        lines.append(f"{team:<20} {g['sessions']:>8} {g['total_usd']:>10.4f}  {tasks}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Cost attribution by team (join-side)")
    ap.add_argument("--corpus", default="corpus")
    ap.add_argument("--join", required=True, help="sessions.csv registry (session_id,team)")
    ap.add_argument("--group-by", choices=("team", "task", "tag"), default="team")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    records = load_corpus_records(args.corpus)
    if args.group_by == "task":
        records = [dict(r, session_id=r.get("task_type", "coding")) for r in records]
        mapping = {str(r.get("task_type", "coding")): str(r.get("task_type", "coding"))
                   for r in records}
    elif args.group_by == "tag":
        # Capture-side tags: group key is the sorted comma-joined tag set
        # ("untagged" when empty). Multi-tag sessions count once, never double.
        records = [
            dict(r, session_id=",".join(sorted(r.get("session_tags", []) or [])) or "untagged")
            for r in records
        ]
        mapping = {str(r["session_id"]): str(r["session_id"]) for r in records}
    else:
        mapping = load_mapping(args.join)
    groups = rollup(records, mapping)
    print(json.dumps(groups, indent=2) if args.json else render_table(groups))
    return 0


__all__ = ["main", "render_table"]
