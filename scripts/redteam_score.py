#!/usr/bin/env python3
"""Score a directory of (red-team) traces and rank models by calmness.

Usage:
    uv run python scripts/redteam_score.py --traces DIR [--json]

Groups scored traces by bundle model. Standalone: needs no Hermes install —
input is a plain directory of trace .py files (sidecars reused when present).
Glue script — verified ad-hoc, no unit test.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pulse.leaderboard_cli import load_corpus_records
from pulse.redteam import calmness


def main() -> int:
    ap = argparse.ArgumentParser(description="Rank models by red-team calmness")
    ap.add_argument("--traces", default="corpus")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    records = load_corpus_records(args.traces)
    by_model: dict[str, list[dict]] = {}
    for rec in records:
        by_model.setdefault(rec.get("model", "?") or "?", []).append(rec)
    rows = calmness(by_model)
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("No scored traces found.")
        return 0
    print(f"{'model':<24} {'n':>3} {'mean':>6} {'frust/10':>8} {'corr/10':>8} {'reas/10':>8}")
    for r in rows:
        print(f"{r['model']:<24} {r['sessions']:>3} {r['mean_score']:>6} "
              f"{r['frustration_per_10']:>8} {r['correction_chain_per_10']:>8} "
              f"{r['reasoning_loop_per_10']:>8}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
