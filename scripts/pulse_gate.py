#!/usr/bin/env python3
"""Pulse quality gate: fail the build when candidate corpus regresses vs baseline.

Usage:
    uv run python scripts/pulse_gate.py --baseline corpus/main --candidate corpus/pr [--tolerance 5.0]

Exit 0 on pass, 1 on fail. Prints a human-readable per-task delta table.
Glue script — verified ad-hoc (both paths), no unit test.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pulse.gate import compare
from pulse.leaderboard_cli import load_corpus_records


def main() -> int:
    ap = argparse.ArgumentParser(description="Pulse quality gate: baseline vs candidate corpora")
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--tolerance", type=float, default=5.0)
    args = ap.parse_args()

    baseline = load_corpus_records(args.baseline)
    candidate = load_corpus_records(args.candidate)
    result = compare(baseline, candidate, tolerance=args.tolerance)

    status = "PASS" if result["pass"] else "FAIL"
    print(f"Pulse gate: {status}  baseline={result['baseline_mean']} "
          f"candidate={result['candidate_mean']} delta={result['delta']} "
          f"(tolerance={args.tolerance})")
    print(f"{'task':<12} {'baseline':>8} {'candidate':>9} {'drop':>6}")
    for task, d in sorted(result["detail"].items()):
        print(f"{task:<12} {d['baseline']:>8} {d['candidate']:>9} {d['drop']:>6}")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
