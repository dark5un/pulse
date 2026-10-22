"""`pulse corpus` implementation: export / list / select (deep-judge gate M2+M3).

export  -> hashed redacted snapshots from the session DB (read-only) + index
list    -> human-readable view of the index sidecar (the pinned corpus)
select  -> stratified run manifest (random core + enriched half, per-pair
           detector-positive floors); membership is run-frozen.

Loud-failure contract (M0, export half): missing/locked DB and unreadable
corpus name the resolved path and exit 2 — never a silent empty result.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .corpus import (
    CorpusError,
    SelectionError,
    default_manifest_path,
    export_corpus,
    read_index,
    select_corpus,
)
from .session_store import SchemaIncompatibleError


def _render_index(corpus_dir: Path, index: dict[str, Any], show_all: bool) -> str:
    entries = index.get("entries", {})
    lines = [
        (
            f"corpus: {corpus_dir}  index written {index.get('written_at', '?')}  "
            f"pulse {index.get('pulse_version', '?')}  redact {index.get('redact_version', '?')}"
        ),
        f"{'hash16':<18}{'session_id':<22}{'model':<26}{'task':<12}{'msgs':>6}  exported_at            flags",
    ]
    active = 0
    for name in sorted(entries):
        e = entries[name]
        superseded = bool(e.get("superseded_by"))
        if superseded and not show_all:
            continue
        active += 1
        flags = []
        if superseded:
            flags.append(f"superseded-by {e['superseded_by']}")
        else:
            if not (corpus_dir / name).exists():
                flags.append("MISSING-FILE")
            if e.get("approx_truncated"):
                flags.append("truncates-under-12k")
        lines.append(
            f"{name.removesuffix('.json'):<18}{str(e.get('session_id', '?'))[:20]:<22}"
            f"{str(e.get('model', ''))[:24]:<26}{str(e.get('task_type', ''))[:10]:<12}"
            f"{e.get('message_count', 0):>6}  {str(e.get('exported_at', ''))[:19]:<21}"
            f"{' ; '.join(flags)}"
        )
    lines.append(f"{active} snapshot(s) listed ({'all incl. superseded' if show_all else 'active only; --all shows superseded'})")
    return "\n".join(lines)


def _cmd_export(args: argparse.Namespace) -> int:
    summary = export_corpus(args.out, db_path=args.db or None, limit=args.limit)
    if args.json:
        print(json.dumps(asdict(summary), indent=2))
    else:
        print(f"db: {summary.db_path}")
        print(summary.line())
        print(f"snapshots + index.json -> {summary.corpus_dir} (never git-tracked; .gitignore ships corpus/)")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    corpus_dir = Path(args.corpus)
    index = read_index(corpus_dir)
    if args.json:
        print(json.dumps(index, indent=2, sort_keys=True))
    else:
        print(_render_index(corpus_dir, index, args.all))
    return 0


def _cmd_select(args: argparse.Namespace) -> int:
    corpus_dir = Path(args.corpus)
    out = Path(args.out) if args.out else default_manifest_path(corpus_dir)
    manifest = select_corpus(
        corpus_dir,
        n_core=args.n_core,
        n_enriched=args.n_enriched,
        pair_floor=args.pair_floor,
        seed=args.seed,
        out_path=out,
    )
    counts = manifest["counts"]
    if args.json:
        print(json.dumps({"manifest": str(out), "counts": counts}, indent=2))
    else:
        print(f"eligible={counts['eligible']} deduped={counts['deduped']} "
              f"selected core={counts['core']} enriched={counts['enriched']} (seed={manifest['seed']})")
        for pair, per in counts["det_positive"].items():
            floor = manifest["params"]["pair_floor"]
            ok = "MEETS" if per["total"] >= floor else "BELOW"
            print(f"  pair {pair}: detector-positive core={per['core']} enriched={per['enriched']} "
                  f"total={per['total']} vs floor {floor} -> {ok}")
        print(f"manifest -> {out}")
        print("floors here are DETECTOR-positive; judge-positive floors are re-checked at agreement time. "
              "Membership is run-frozen: re-pin = new manifest, never an edit.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pulse corpus", description="Pulse-owned redacted snapshot corpus")
    sub = ap.add_subparsers(dest="cmd", required=True)

    exp = sub.add_parser("export", help="export session DB -> hashed redacted snapshots (incremental)")
    exp.add_argument("--out", default="corpus", help="corpus dir (default ./corpus; never git-tracked)")
    exp.add_argument("--db", default="", help="session DB path (default: $HERMES_HOME/state.db)")
    exp.add_argument("--limit", type=int, default=0, help="only the most recent N sessions (dry-run aid)")
    exp.add_argument("--json", action="store_true")

    lst = sub.add_parser("list", help="show the corpus index (hash -> session_id, model, task_type, exported_at)")
    lst.add_argument("--corpus", default="corpus")
    lst.add_argument("--all", action="store_true", help="include superseded snapshot versions")
    lst.add_argument("--json", action="store_true")

    sel = sub.add_parser("select", help="stratified selection -> frozen run manifest")
    sel.add_argument("--corpus", default="corpus")
    sel.add_argument("--out", default="", help="manifest path (default corpus/manifests/manifest-<UTC>.json)")
    sel.add_argument("--n-core", type=int, default=50)
    sel.add_argument("--n-enriched", type=int, default=50)
    sel.add_argument("--pair-floor", type=int, default=10)
    sel.add_argument("--seed", type=int, default=20261022)
    sel.add_argument("--json", action="store_true")

    args = ap.parse_args(argv)
    try:
        if args.cmd == "export":
            return _cmd_export(args)
        if args.cmd == "list":
            return _cmd_list(args)
        if args.cmd == "select":
            return _cmd_select(args)
    except (SchemaIncompatibleError, CorpusError, SelectionError) as e:
        print(f"pulse corpus {args.cmd}: {e}")
        return 2
    ap.error(f"unknown corpus command: {args.cmd}")
    return 2


__all__ = ["main"]
