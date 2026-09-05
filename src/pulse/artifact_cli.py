"""`pulse bundle` + `pulse verify` implementations (plan item 4 / B4)."""

from __future__ import annotations

import argparse

from pulse.artifact import bundle, verify


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Bundle a trace as a paper artifact")
    ap.add_argument("trace", help="Trace .py file")
    ap.add_argument("--out", default=".")
    args = ap.parse_args(argv)
    print(bundle(args.trace, out_dir=args.out))
    return 0


def verify_main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify a trace artifact replays + rescores")
    ap.add_argument("artifact", help="Artifact dir from pulse bundle")
    args = ap.parse_args(argv)
    out = verify(args.artifact)
    status = "replays" if out["replays"] else "REPLAY FAILED"
    score = "score reproduces" if out["score_reproduces"] else "SCORE DIFFERS"
    print(f"{status}, {score}: {out['detail']}")
    return 0 if out["replays"] and out["score_reproduces"] else 1


__all__ = ["main", "verify_main"]
