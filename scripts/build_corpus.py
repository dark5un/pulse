#!/usr/bin/env python3
"""Curate a regression corpus: pulse-score all unroll traces, keep bottom-10.

Usage:
    uv run python scripts/build_corpus.py [--traces DIR] [--out DIR]

Each kept trace is copied into the corpus dir with a sidecar JSON holding
its score, signals, cost, and model. Glue script — verified ad-hoc, no unit test.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pulse.signals import extract_signals
from pulse.signals_unroll import detect_cost, detect_latency, detect_skill_deadweight
from pulse.unroll_loader import bundle_to_messages, load_unroll_trace


def score_trace(path: Path) -> dict:
    bundle = load_unroll_trace(str(path))
    messages = bundle_to_messages(bundle)
    result = extract_signals(messages)
    task_type = result.metrics.get("task_type", "coding")
    unroll_sigs = (
        detect_latency(bundle)
        + detect_cost(bundle, task_type)
        + detect_skill_deadweight(bundle, messages)
    )
    all_sigs = list(result.signals) + unroll_sigs
    penalty = sum(s.penalty for s in all_sigs)
    score = max(0, min(100, round(100 - penalty)))
    return {
        "path": str(path),
        "session_id": bundle.session_id,
        "model": bundle.model,
        "score": score,
        "penalty": penalty,
        "cost_usd": bundle.cost_usd,
        "task_type": task_type,
        "signals": [{"name": s.name, "severity": s.severity, "penalty": s.penalty,
                     "label": s.label, "evidence": s.evidence[:2]} for s in all_sigs],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Build pulse regression corpus from unroll traces")
    ap.add_argument("--traces", default=str(Path.home() / ".hermes" / "traces" / "unrolled"))
    ap.add_argument("--out", default="corpus")
    ap.add_argument("--keep", type=int, default=10)
    args = ap.parse_args()

    trace_dir = Path(args.traces)
    out_dir = Path(args.out)
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
