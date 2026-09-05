"""`pulse replay` implementation: replay every trace in a corpus dir.

Exit 0 when all traces replay clean, 1 otherwise. Dry-run by default
(traces replay from cache); ``--live`` executes real LLM calls.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .replay import replay_corpus


def find_traces(corpus: str | Path) -> list[str]:
    """Sorted ``*.py`` trace paths in a corpus dir (sidecars excluded)."""
    d = Path(corpus)
    if not d.is_dir():
        raise SystemExit(f"corpus dir not found: {d}")
    return [str(p) for p in sorted(d.glob("*.py"))]


def render_json(rows: list[dict]) -> str:
    return json.dumps(rows, indent=2)


def render_table(rows: list[dict]) -> str:
    if not rows:
        return "No traces found."
    lines = []
    failed = 0
    for r in rows:
        name = Path(str(r["trace"])).name
        if r["timed_out"]:
            status, failed = "TIMEOUT", failed + 1
        elif r["ok"]:
            status = "PASS"
        else:
            status, failed = f"FAIL({r['returncode']})", failed + 1
        lines.append(f"{status:<9} {name}")
    lines.append(f"{len(rows) - failed}/{len(rows)} passed, {failed} failed")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Replay every trace in a corpus")
    ap.add_argument("--corpus", default="corpus")
    ap.add_argument("--live", action="store_true", help="Execute real LLM calls")
    ap.add_argument("--timeout", type=int, default=300, help="Per-trace seconds")
    ap.add_argument("--jobs", type=int, default=4, help="Parallel workers")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rows = replay_corpus(
        find_traces(args.corpus), live=args.live, timeout=args.timeout, jobs=args.jobs
    )
    print(render_json(rows) if args.json else render_table(rows))
    return 0 if all(r["ok"] for r in rows) else 1


__all__ = ["find_traces", "main", "render_json", "render_table"]
