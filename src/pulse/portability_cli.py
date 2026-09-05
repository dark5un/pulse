"""`pulse portability` implementation: skill verdicts over a corpus dir."""

from __future__ import annotations

import argparse
import json

from pulse.leaderboard_cli import load_corpus_records
from pulse.portability import portability


def render_portability(records: list[dict], *, as_json: bool = False) -> str:
    result = portability(records)
    if as_json:
        return json.dumps(result, indent=2)
    if not result:
        return "No skill data found (no active_skills in corpus records)."
    lines = []
    for skill in sorted(result):
        models = ", ".join(f"{m}={r}" for m, r in sorted(result[skill]["models"].items()))
        lines.append(f"{skill:<24} {result[skill]['verdict']:<14} {models}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Cross-model skill portability over a corpus")
    ap.add_argument("--corpus", default="corpus")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    print(render_portability(load_corpus_records(args.corpus), as_json=args.json))
    return 0


__all__ = ["main", "render_portability"]
