"""`pulse leaderboard` implementation: load sidecars, render table/JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pulse.leaderboard import rank_traces
from pulse.trace_score import score_trace_file


def load_corpus_records(corpus: str | Path) -> list[dict]:
    """Load ``*.score.json`` sidecars; score ``*.py`` traces live as fallback."""
    d = Path(corpus)
    if not d.is_dir():
        raise SystemExit(f"corpus dir not found: {d}")
    records: list[dict] = []
    for sidecar in sorted(d.glob("*.score.json")):
        try:
            records.append(json.loads(sidecar.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    scored_stems = {Path(str(r.get("path", ""))).stem for r in records}
    scored_stems |= {p.stem.replace(".score", "") for p in d.glob("*.score.json")}
    for trace in sorted(d.glob("*.py")):
        if trace.stem in scored_stems:
            continue
        try:
            records.append(score_trace_file(trace))
        except Exception as e:  # noqa: BLE001 — glue, skip unloadable traces
            print(f"skip {trace.name}: {e}")
            continue
    return records


def render_leaderboard(records: list[dict], *, as_json: bool = False) -> str:
    ranked = rank_traces(records)
    if as_json:
        return json.dumps(ranked, indent=2)
    if not ranked:
        return "No scored traces found."
    lines = []
    for task in sorted(ranked):
        lines.append(f"== {task} ({len([r for r in records if r.get('task_type') == task])} traces) ==")
        for bucket in ("best", "worst"):
            lines.append(f"  {bucket.upper()}:")
            for e in ranked[task][bucket]:  # type: ignore[literal-required]
                sigs = ",".join(e["signals"][:3])
                lines.append(f"    {e['score']:>3}  {e['id_hash']}  {e['model'] or '?':<12} {sigs}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Rank scored traces per task type")
    ap.add_argument("--corpus", default="corpus")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    print(render_leaderboard(load_corpus_records(args.corpus), as_json=args.json))
    return 0


__all__ = ["load_corpus_records", "main", "render_leaderboard"]
