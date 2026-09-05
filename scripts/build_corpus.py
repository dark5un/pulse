#!/usr/bin/env python3
"""Curate a regression corpus: pulse-score all unroll traces, keep bottom-10.

Usage:
    uv run python scripts/build_corpus.py [--traces DIR] [--out DIR]

Each kept trace is copied into the corpus dir with a sidecar JSON holding
its score, signals, cost, and model. Glue script — verified ad-hoc, no unit test.
Scoring lives in src/pulse/trace_score.py (shared with leaderboard/gates).
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pulse.trace_score import score_trace_file


def score_trace(path: Path) -> dict:
    """Thin wrapper kept for backwards-compat; see pulse.trace_score."""
    return score_trace_file(path)


def main() -> int:
    ap = argparse.ArgumentParser(description="Build pulse regression corpus from unroll traces")
    ap.add_argument("--traces", default=str(Path.home() / ".hermes" / "traces" / "unrolled"))
    ap.add_argument("--out", default="corpus")
    ap.add_argument("--keep", type=int, default=10)
    args = ap.parse_args()

    trace_dir = Path(args.traces)
    out_dir = Path(args.out)
    try:
        same_dir = trace_dir.resolve() == out_dir.resolve()
    except OSError:
        same_dir = False
    traces = sorted(trace_dir.glob("*.py")) if trace_dir.is_dir() else []
    if not traces:
        print(f"No traces found in {trace_dir}")
        return 1
    scored = []
    for t in traces:
        try:
            scored.append(score_trace(t))
        except Exception as e:  # noqa: BLE001 — glue script, report and continue
            print(f"skip {t.name}: {e}")
    if same_dir:
        # Refresh mode: rescore in place, rewrite every sidecar, copy nothing.
        out_dir.mkdir(parents=True, exist_ok=True)
        for rec in scored:
            src = Path(rec["path"])
            (out_dir / (src.stem + ".score.json")).write_text(json.dumps(rec, indent=2))
        print(f"refreshed {len(scored)} sidecars in {out_dir}")
        return 0
    scored.sort(key=lambda r: r["score"])
    kept = scored[: args.keep]
    out_dir.mkdir(parents=True, exist_ok=True)
    for rec in kept:
        src = Path(rec["path"])
        shutil.copy(src, out_dir / src.name)
        (out_dir / (src.stem + ".score.json")).write_text(json.dumps(rec, indent=2))
        print(f"{rec['score']:>3}  ${rec['cost_usd']:.4f}  {src.name}  {[s['name'] for s in rec['signals']]}")
    print(f"kept {len(kept)}/{len(scored)} in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
