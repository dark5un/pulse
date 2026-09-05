"""`pulse incident` + `pulse flake` implementations (plan item 5 / C1+C3)."""

from __future__ import annotations

import argparse
import json

from pulse.flake import flake
from pulse.flake import render as render_flake
from pulse.incident import render, skeleton


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Incident postmortem skeleton for a trace")
    ap.add_argument("--trace", required=True)
    ap.add_argument("--bad-step", type=int, required=True)
    ap.add_argument("--window", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        skel = skeleton(args.trace, bad_step=args.bad_step, window=args.window)
    except ValueError as e:
        raise SystemExit(str(e)) from e
    print(json.dumps(skel, indent=2) if args.json else render(skel))
    return 0


def flake_main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Divergence map: replay a trace N times")
    ap.add_argument("--trace", required=True)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rows = flake([args.trace] * args.runs, timeout=args.timeout)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print(render_flake(rows))
    return 0 if all(r["verdict"] == "stable" for r in rows) else 1


__all__ = ["flake_main", "main"]
