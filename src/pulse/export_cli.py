"""`pulse export` implementation: corpus -> SFT + DPO pairs on disk."""

from __future__ import annotations

import argparse
from pathlib import Path

from pulse.export import bundle_to_sharegpt, correction_pairs, export_records
from pulse.leaderboard_cli import load_corpus_records
from pulse.unroll_loader import load_unroll_trace


def _messages_for(rec: dict) -> list[dict]:
    """Trace messages when the .py exists, else ShareGPT-shaped sidecar stub."""
    path = rec.get("path", "")
    if path and Path(str(path)).exists():
        try:
            return bundle_to_sharegpt(load_unroll_trace(str(path)))
        except Exception as e:  # noqa: BLE001 — fall back to stub below
            print(f"skip {path}: {e}")
    return [{"role": "user", "content": ""}]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Export corpus as SFT + DPO training data")
    ap.add_argument("--corpus", default="corpus")
    ap.add_argument("--out", default="export")
    ap.add_argument("--format", choices=("sharegpt", "jsonl"), default="sharegpt")
    ap.add_argument("--min-score", type=int, default=90)
    ap.add_argument(
        "--review",
        action="store_true",
        help="Dump mined DPO pairs for human spot-check instead of writing files",
    )
    args = ap.parse_args(argv)
    records = load_corpus_records(args.corpus)
    messages_by_id = {str(r.get("session_id", "")): _messages_for(r) for r in records}
    if args.review:
        n = 0
        for sid, msgs in sorted(messages_by_id.items()):
            for pair in correction_pairs(msgs):
                n += 1
                print(f"--- pair {n} ({sid}) ---")
                print(f"PROMPT:   {pair['prompt'][:200]}")
                print(f"REJECTED: {pair['rejected'][:200]}")
                print(f"CHOSEN:   {pair['chosen'][:200]}")
        print(f"{n} pairs — spot-check before training; not every correction is clean")
        return 0
    manifest = export_records(
        records, messages_by_id, args.out, fmt=args.format, min_score=args.min_score
    )
    print(
        f"kept={manifest['kept']} dropped={manifest['dropped']} "
        f"-> {args.out}/sft.jsonl + pairs.jsonl ({manifest['redaction_receipt']})"
    )
    return 0


__all__ = ["main"]
