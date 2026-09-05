"""`pulse experiment` implementation: corpus -> manifest + results dir."""

from __future__ import annotations

import argparse
from pathlib import Path

from pulse.compare import compare_distributions
from pulse.experiment import write_manifest
from pulse.leaderboard_cli import load_corpus_records


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Pin an experiment corpus with manifest")
    ap.add_argument("--corpus", default="corpus")
    ap.add_argument("--out", required=True, help="Results dir for manifest")
    ap.add_argument("--variable", required=True, help="Swept variable, e.g. model=m2")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    records = load_corpus_records(args.corpus)
    traces = [str(r.get("path", "")) for r in records if r.get("path")]
    manifest = write_manifest(args.out, traces, variable=args.variable)
    if args.json:
        import json

        print(json.dumps(manifest, indent=2))
    else:
        scores = [float(r.get("score", 0)) for r in records]
        from pulse.compare import summarize

        s = summarize(scores)
        print(f"variable={args.variable} n={s['n']} mean={s['mean']} -> {args.out}")
    Path(args.out, "records.json").write_text(
        __import__("json").dumps(
            {"records": records, "baseline": compare_distributions(records, records)},
            indent=2,
        )
    )
    return 0


__all__ = ["main"]
