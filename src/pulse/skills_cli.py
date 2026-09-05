"""`pulse skills` implementation: ROI ledger over a corpus dir."""

from __future__ import annotations

import argparse
import json

from .leaderboard_cli import load_corpus_records
from .skills import ledger


def render_json(records: list[dict]) -> str:
    return json.dumps(ledger(records), indent=2)


def render(records: list[dict]) -> str:
    cards = ledger(records)
    if not cards:
        return "No skill data found (no active_skills in corpus records)."
    lines = [
        (
            f"{'skill':<24} {'loads':>5} {'dw_rate':>7} {'corr_rate':>9} "
            f"{'mean_cost':>9} {'task_mix'}"
        )
    ]
    for skill in sorted(cards):
        c = cards[skill]
        mix = ",".join(f"{t}:{n}" for t, n in sorted(c["task_mix"].items()))
        lines.append(
            f"{skill:<24} {c['loads']:>5} {c['deadweight_rate']:>7} "
            f"{c['correction_rate']:>9} {c['mean_cost']:>9.4f} {mix}"
        )
        if c["baseline_cost_same_task"]:
            lines.append(
                f"{'':<24} baseline skill-less cost (same tasks): "
                f"${c['baseline_cost_same_task']:.4f} — correlation, not causation"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Per-skill ROI ledger over a corpus")
    ap.add_argument("--corpus", default="corpus")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    records = load_corpus_records(args.corpus)
    print(render_json(records) if args.json else render(records))
    return 0


__all__ = ["main", "render", "render_json"]
