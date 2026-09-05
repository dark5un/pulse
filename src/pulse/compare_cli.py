"""`pulse compare` implementation: distributions over two corpora + verdict."""

from __future__ import annotations

import argparse
import json

from .compare import compare_distributions
from .leaderboard_cli import load_corpus_records


def render(a: list[dict], b: list[dict], aname: str, bname: str) -> str:
    out = compare_distributions(a, b)
    lines = [f"{aname} (n={out['a']['n']}) vs {bname} (n={out['b']['n']})"]
    lines.append(f"{'':<8} {'mean':>6} {'median':>6} {'p25':>6} {'p75':>6}")
    for label, s in (("A", out["a"]), ("B", out["b"])):
        lines.append(
            f"{label:<8} {s['mean']:>6} {s['median']:>6} {s['p25']:>6} {s['p75']:>6}"
        )
    lines.append(f"score delta (A-B): {out['score_delta']:+.1f} pts")
    lines.append(f"cost delta (A-B):  {out['cost_delta']:+.4f} USD mean")
    if out["timing_a"]["n"] and out["timing_b"]["n"]:
        lines.append(f"timing delta (A-B): {out['timing_delta']:+.1f} ms mean")
    lines.append(out["verdict"])
    return "\n".join(lines)


def render_json(a: list[dict], b: list[dict], aname: str, bname: str) -> str:
    out = compare_distributions(a, b)
    out["a_name"], out["b_name"] = aname, bname
    return json.dumps(out, indent=2)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compare score distributions of two corpora")
    ap.add_argument("--a", required=True, help="First corpus dir")
    ap.add_argument("--b", required=True, help="Second corpus dir")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    a = load_corpus_records(args.a)
    b = load_corpus_records(args.b)
    print(render_json(a, b, args.a, args.b) if args.json else render(a, b, args.a, args.b))
    return 0


__all__ = ["main", "render", "render_json"]
