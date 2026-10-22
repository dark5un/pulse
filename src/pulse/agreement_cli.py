"""`pulse agreement` v2 (M4): judge-vs-deterministic on a pinned manifest.

DATA PLANE (CW-5a): consumes a selection manifest (`pulse corpus select`)
plus the hashed redacted snapshot files it pins (`pulse corpus export`).
The old unroll-trace gate path is REPLACED, not flag-coaxed — pre-1.0
breaking CLI surface, CHANGELOG-documented at release. Membership is
run-frozen (ADR 0004): every snapshot's sha256 is checked against the
manifest before any judge call; missing snapshots fail loudly with
"K of N missing; re-run pulse corpus export". Detector labels are ALWAYS
recomputed via `extract_signals` on snapshot messages at run time
(ML-B7 — the snapshot advisory sidecar is never the kappa input).
`--limit` below the manifest's n still runs (dry-run aid) but the verdict
is labeled "below-manifest sample, gate not evaluated" — never a bare
gate FAIL.

REPORTING (CW-5b / ADR 0009): kappa per PAIR per STRATUM (4 cells); the
gate number = min over cells at kappa>=0.6 with post-exclusion n>=50 per
cell. Every cell prints its distribution block (n, per-rater marginals,
confusion cells, abstain rate, post-exclusion n, truncation) BEFORE any
kappa; kappa is REFUSED on degenerate labels (the pe=1 -> 0.0 sentinel
never reaches the gate as a bare FAIL — ML-B6); abstain share above the
provisional MAX_EXCLUSION_SHARE guard -> "not evaluated — exclusion share
too high"; bootstrap 95% CIs (stdlib random) beside every printed kappa
with BORDERLINE when the CI straddles 0.6; pooled cross-stratum kappa is
an explicitly-labeled descriptive line only.

Exit contract: 0 = gate PASS, 1 = gate FAIL, 2 = run failure OR gate NOT
EVALUATED (manifest/missing-snapshot/budget/judge-call failure, cell
refusals, or a below-manifest sample). A refusal is never a FAIL.

Failure contract (M0): a judge/backend CALL failure is loud — exit 2
naming the failed snapshot. The verdict cache is flushed PER RECORD, so
a rerun resumes from cache (one dead endpoint at snapshot #40/50 costs
1 session, not 40).

Cache format (v2): key = sha256(snapshot file bytes + PROMPT_VERSION)[:16]
(file bytes are content-addressed — the manifest sha IS the corpus pin);
VALUE = {signal: finding} — finding-aware (yes|no|unscoreable), because
signal-names alone lose the abstain distinction. PROMPT_VERSION is part
of the key, so v1 list-valued entries can never collide with v2 dicts.

Polarity (ADR 0012, pinned by truth-table tests in test_agreement_polarity):
the v2 prompt defines finding="yes" as "the PROBLEM was found", and a
detector-positive row (correction_chain / premature_stop present) IS an
instance of that problem — so judge-positive (finding=yes) pairs with
detector-present; finding=no is judge-negative; unscoreable or an ABSENT
verdict abstains and is excluded from that pair's kappa only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from .agreement import (
    STRATA,
    CellStats,
    cell_stats,
    gate_verdict,
    pooled_descriptive,
    render_cell,
)
from .corpus import MANIFEST_SCHEMA, SNAPSHOT_SCHEMA
from .judge import JUDGE_MODEL_DEFAULT, OpenAIJudge
from .signals import extract_signals
from .signals_deep import (
    PROMPT_VERSION,
    JudgeBudgetError,
    JudgeCallError,
    JudgeRun,
    resolve_prompt_budget,
    run_judge,
)

#: kappa pairs: deterministic signal -> judge signal whose finding=yes
#: means the same problem was found (polarity per ADR 0012).
PAIR_SIGNAL = {
    "correction_chain": "correction_quality",
    "premature_stop": "goal_completion",
}
#: non-overlapping judge signals: rate readouts only, never kappa.
RATE_SIGNALS = ("hallucination", "context_retention")


def make_backend(args):
    return OpenAIJudge(
        model=args.judge_model or JUDGE_MODEL_DEFAULT, base_url=args.judge_base_url
    )


def _flush_cache(cache_path: Path, cache: dict) -> None:
    try:
        cache_path.write_text(json.dumps(cache, indent=2))
    except OSError as e:
        print(f"warning: could not write cache: {e}")


def _det_labels(messages: list[dict], task_type: str | None = None) -> dict[str, int]:
    # task_type comes from the snapshot stamp: detect_task_type needs
    # tool_calls, which corpus snapshots deliberately lack (re-detecting
    # on the skeleton misclassifies question-heavy coding sessions as
    # brainstorm and silently gates the pair detectors off — ADR 0018).
    names = {s.name for s in extract_signals(messages, task_type).signals}
    return {
        "correction_chain": 1 if "correction_chain" in names else 0,
        "premature_stop": 1 if "premature_stop" in names else 0,
    }


def _pair_label(finding: str | None) -> int | None:
    """Judge label from a v2 finding. None = abstain (unscoreable OR an
    absent verdict — omission must never launder into 'no')."""
    if finding == "yes":
        return 1
    if finding == "no":
        return 0
    return None


def _labels_from_findings(findings: dict[str, str]) -> dict[str, int | None]:
    """Map a finding-aware cache value / JudgeRun.findings to pair + rate
    labels with the pinned polarity (ADR 0012)."""
    out: dict[str, int | None] = {
        pair: _pair_label(findings.get(sig)) for pair, sig in PAIR_SIGNAL.items()
    }
    for sig in RATE_SIGNALS:
        out[f"_{sig}_rate"] = _pair_label(findings.get(sig))
    return out


def _load_manifest(path: Path) -> tuple[dict, str] | str:
    """Return (manifest, sha256) or an error string — validated loudly."""
    try:
        raw = path.read_bytes()
        manifest = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        return f"cannot read manifest {path}: {e}"
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        return (
            f"manifest schema mismatch at {path}: expected {MANIFEST_SCHEMA!r} — "
            "produce it with `pulse corpus select`"
        )
    if manifest.get("prompt_version") != PROMPT_VERSION:
        return (
            f"manifest pins prompt_version={manifest.get('prompt_version')!r} but this "
            f"build speaks {PROMPT_VERSION!r}: verdicts are not comparable — "
            "re-pin with a new manifest (never edit one)"
        )
    items = manifest.get("items")
    if not isinstance(items, list) or not items:
        return f"manifest carries no items: {path}"
    return manifest, hashlib.sha256(raw).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Judge-vs-deterministic agreement gate (v2: pinned manifest + snapshots)"
    )
    ap.add_argument(
        "--manifest",
        required=True,
        help="selection manifest from `pulse corpus select` (run-frozen membership)",
    )
    ap.add_argument(
        "--corpus",
        default="",
        help="snapshot dir (default: the manifest's corpus_dir)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="judge only the first N manifest items (dry-run aid; below-manifest n "
        "is labeled 'gate not evaluated', never a bare FAIL)",
    )
    ap.add_argument("--cache", default=".pulse_agreement_cache.json")
    ap.add_argument("--judge-model", default="")
    ap.add_argument("--judge-base-url", default="")
    ap.add_argument(
        "--judge-context",
        type=int,
        default=0,
        help="explicit judge context window (tokens); overrides the manifest "
        "judge.context_window, the PULSE_JUDGE_CONTEXT env and the read-only "
        "/v1/models probe (ADR 0010/0013)",
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    loaded = _load_manifest(Path(args.manifest))
    if isinstance(loaded, str):
        print(f"manifest failure: {loaded}", file=sys.stderr)
        return 2
    manifest, manifest_sha = loaded
    items: list[dict] = manifest["items"]
    corpus_dir = Path(args.corpus or manifest.get("corpus_dir") or "corpus")

    below_manifest = 0 < args.limit < len(items)
    selected = items[: args.limit] if args.limit > 0 else items

    # Frozen membership check BEFORE any GPU time: every manifest-listed
    # snapshot must exist and match its pinned sha256.
    missing = [it["path"] for it in selected if not (corpus_dir / str(it["path"])).exists()]
    if missing:
        print(
            f"corpus snapshot failure: {len(missing)} of {len(selected)} missing; "
            f"re-run pulse corpus export (dir: {corpus_dir}; first: {missing[0]})",
            file=sys.stderr,
        )
        return 2
    raw_by_path: dict[str, bytes] = {}
    for it in selected:
        raw = (corpus_dir / str(it["path"])).read_bytes()
        if hashlib.sha256(raw).hexdigest() != it.get("sha256"):
            print(
                f"corpus integrity failure: {it['path']} content hash != manifest "
                "sha256 — the pinned corpus moved; a re-pin is a NEW manifest, never "
                "an edit (re-run pulse corpus select)",
                file=sys.stderr,
            )
            return 2
        raw_by_path[str(it["path"])] = raw

    # Judge identity: CLI flag -> manifest record (the manifest pins model +
    # endpoint + context window; ADR 0013 resolution order).
    jid = manifest.get("judge") or {}
    if not args.judge_model:
        args.judge_model = str(jid.get("model") or "")
    if not args.judge_base_url:
        args.judge_base_url = str(jid.get("base_url") or "")
    backend = make_backend(args)
    try:
        budget = resolve_prompt_budget(
            backend, args.judge_context or jid.get("context_window") or None
        )
    except JudgeBudgetError as e:
        print(f"judge budget failure: {e}", file=sys.stderr)
        return 2
    print(
        f"judge prompt budget: {budget.budget_chars} chars "
        f"(source={budget.source}, context_window_tokens={budget.context_window_tokens})",
        file=sys.stderr,
    )

    cache_path = Path(args.cache)
    try:
        cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    except (json.JSONDecodeError, OSError):
        cache = {}

    # rows[stratum][pair] = list of (judge|None, det, approx, trunc|None)
    strata_seen: list[str] = []
    rows: dict[str, dict[str, list[tuple]]] = {}
    for item in selected:
        st = str(item.get("stratum", "core"))
        if st not in strata_seen:
            strata_seen.append(st)
        rows.setdefault(st, {pair: [] for pair in PAIR_SIGNAL})
    rate_pos = {sig: 0 for sig in RATE_SIGNALS}
    rate_n = {sig: 0 for sig in RATE_SIGNALS}
    n = 0
    ineligible = 0
    cache_hits = 0
    runs: list[JudgeRun] = []
    durations: list[float] = []
    tokens_in = tokens_out = 0
    t_run = time.monotonic()

    for i, item in enumerate(selected, 1):
        name = str(item["path"])
        raw = raw_by_path[name]
        payload = json.loads(raw)
        if payload.get("schema") != SNAPSHOT_SCHEMA:
            print(
                f"corpus integrity failure: {name} snapshot schema mismatch "
                f"(expected {SNAPSHOT_SCHEMA!r}) — re-run pulse corpus export",
                file=sys.stderr,
            )
            return 2
        messages = list(payload.get("messages") or [])
        stratum = str(item.get("stratum", "core"))
        # ML-B7: kappa input recomputed at run time, never the advisory
        # sidecar (detector thresholds can drift between export and run).
        # task_type is taken from the snapshot stamp — the skeleton has no
        # tool_calls, so re-detecting it here would gate detectors wrongly
        # (ADR 0018).
        stamp_task = str(payload.get("task_type") or "") or None
        det = extract_signals(messages, stamp_task)
        if det.skipped_reason:
            ineligible += 1
            print(
                f"run-time ineligible snapshot {name}: {det.skipped_reason} — excluded "
                "from all cells (recomputed via extract_signals, ML-B7)",
                file=sys.stderr,
            )
            continue
        dl = _det_labels(messages, stamp_task)
        key = hashlib.sha256(raw + PROMPT_VERSION.encode()).hexdigest()[:16]
        truncated_measured: bool | None = None
        if isinstance(cache.get(key), dict):
            findings = cache[key]
            cache_hits += 1
            print(f"judge: {i}/{len(selected)} {name} cached", file=sys.stderr)
        else:
            try:
                t0 = time.monotonic()
                run = run_judge(messages, backend, budget=budget)
                dur = time.monotonic() - t0
            except JudgeCallError as e:
                # Loud-failure contract (M0): name the failed snapshot,
                # exit 2; records judged so far are already flushed.
                print(f"judge call failure on snapshot {name}: {e}", file=sys.stderr)
                print(
                    f"verdict cache intact after {n} record(s); a rerun resumes from cache",
                    file=sys.stderr,
                )
                return 2
            durations.append(dur)
            truncated_measured = run.truncated
            for d in run.diagnostics:
                print(f"judge parse diagnostic: {d}", file=sys.stderr)
            runs.append(run)
            usage = getattr(backend, "last_result", None)
            if usage is not None:
                tokens_in += int(getattr(usage, "input_tokens", 0) or 0)
                tokens_out += int(getattr(usage, "output_tokens", 0) or 0)
            print(
                f"judge: {i}/{len(selected)} {name} fresh in {dur:.1f}s "
                f"({run.prompt_chars} chars{', truncated' if run.truncated else ''})",
                file=sys.stderr,
            )
            findings = run.findings
            # v2 cache VALUE is the finding map (yes|no|unscoreable).
            cache[key] = findings
            # Flush per record (M0): an endpoint death at #40/50 must
            # cost one session, not the whole batch.
            _flush_cache(cache_path, cache)
        jl = _labels_from_findings(findings)
        approx = bool(item.get("approx_truncated"))
        for pair in PAIR_SIGNAL:
            rows[stratum][pair].append((jl[pair], dl[pair], approx, truncated_measured))
        for sig in RATE_SIGNALS:
            label = jl[f"_{sig}_rate"]
            if label is not None:
                rate_n[sig] += 1
                rate_pos[sig] += label
        n += 1
    _flush_cache(cache_path, cache)
    wall = time.monotonic() - t_run

    # Every expected cell prints, even an absent stratum (n=0 refusal).
    all_strata = list(STRATA) + [s for s in strata_seen if s not in STRATA]
    # Every expected cell prints, even an absent stratum (n=0 refusal).
    cells: list[CellStats] = []
    for pair in PAIR_SIGNAL:
        for stratum in (all_strata or STRATA):
            cells.append(cell_stats(pair, stratum, rows.get(stratum, {}).get(pair, [])))

    pooled = {
        pair: pooled_descriptive(
            [r for st in all_strata for r in rows.get(st, {}).get(pair, [])]
        )
        for pair in PAIR_SIGNAL
    }
    verdict = gate_verdict(cells, below_manifest_sample=below_manifest)

    grounded = sum(r.grounded for r in runs)
    total_quotes = sum(r.total_quotes for r in runs)
    measurements: dict = {
        "fresh_calls": len(runs),
        "wall_clock_s": round(wall, 1),
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
    }
    if durations:
        measurements["per_call_seconds"] = {
            "mean": round(sum(durations) / len(durations), 1),
            "min": round(min(durations), 1),
            "max": round(max(durations), 1),
        }
    if runs:
        sizes = sorted(r.prompt_chars for r in runs)
        measurements["prompt_chars"] = {
            "min": sizes[0],
            "median": sizes[len(sizes) // 2],
            "mean": round(sum(sizes) / len(sizes)),
            "max": sizes[-1],
            "truncated_fresh": sum(1 for r in runs if r.truncated),
        }

    result: dict = {
        "manifest": {
            "path": str(args.manifest),
            "sha256": manifest_sha,
            "items": len(items),
            "processed": len(selected),
            "strata": {st: sum(1 for it in selected if it.get("stratum") == st) for st in all_strata},
            "seed": manifest.get("seed"),
            "prompt_version": manifest.get("prompt_version"),
            "redact_version": manifest.get("redact_version"),
        },
        "judge": {
            "model": args.judge_model or JUDGE_MODEL_DEFAULT,
            "base_url": args.judge_base_url or "(default)",
            "lane": (manifest.get("judge") or {}).get("lane", "api"),
            "budget": {
                "chars": budget.budget_chars,
                "source": budget.source,
                "context_window_tokens": budget.context_window_tokens,
            },
        },
        "run": {
            "n": n,
            "cache_hits": cache_hits,
            "run_time_ineligible": ineligible,
        },
        "cells": [c.to_dict() for c in cells],
        "pooled_descriptive": pooled,
        "rates": {
            sig: {
                "positive": rate_pos[sig],
                "gradeable": rate_n[sig],
                "rate": round(rate_pos[sig] / rate_n[sig], 3) if rate_n[sig] else None,
            }
            for sig in RATE_SIGNALS
        },
        "evidence_grounding": {
            "grounded": grounded,
            "total": total_quotes,
            "rate": round(grounded / total_quotes, 3) if total_quotes else None,
            "note": "fresh judge calls only (cache hits carry findings, not quotes)",
        },
        "measurements": measurements,
        "gate": verdict,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        mres = result["manifest"]
        print(
            f"manifest: {mres['path']} sha256={manifest_sha}\n"
            f"  items={mres['items']} strata={mres['strata']} seed={mres['seed']} "
            f"prompt={mres['prompt_version']} redact={mres['redact_version']}"
        )
        print(
            f"  judge: {result['judge']['model']} @ {result['judge']['base_url']} "
            f"lane={result['judge']['lane']}"
        )
        print(
            f"run: eligible={n} cache_hits={cache_hits} fresh={len(runs)} "
            f"run-time-ineligible={ineligible}"
        )
        if below_manifest:
            print(
                f"  NOTE: --limit {args.limit} < manifest n={len(items)} — "
                "below-manifest sample, gate not evaluated"
            )
        print()
        for c in cells:
            print("\n".join(render_cell(c)))
        print()
        rate_line = " ".join(
            f"{sig} judge-rate={result['rates'][sig]['rate'] if result['rates'][sig]['rate'] is not None else 'n/a'} "
            f"({rate_pos[sig]}/{rate_n[sig]})"
            for sig in RATE_SIGNALS
        )
        print(f"{rate_line} (spot-check required, never kappa)")
        pct = f" ({100.0 * grounded / total_quotes:.1f}%)" if total_quotes else ""
        print(f"evidence grounding: {grounded}/{total_quotes} quotes grounded{pct}")
        if runs:
            pc = measurements["prompt_chars"]
            print(
                f"prompt size (fresh calls): median={pc['median']} mean={pc['mean']} "
                f"max={pc['max']} truncated={pc['truncated_fresh']}/{len(runs)}"
            )
        for pair, p in pooled.items():
            print(
                f"pooled {pair} (descriptive only — mix-dependent, never the gate): "
                f"kappa={p['kappa']} n={p['n']}"
            )
        g = result["gate"]
        if g["verdict"] == "pass":
            print(
                f"gate: PASS min_cell_kappa={g['min_cell_kappa']} "
                f"(min over {len(cells)} cells; {g['reason']})"
            )
        elif g["verdict"] == "fail":
            print(
                f"gate: FAIL min_cell_kappa={g['min_cell_kappa']} at {g.get('min_cell')} "
                f"(min over {len(cells)} cells; {g['reason']})"
            )
        else:
            print(f"gate: NOT EVALUATED — {g['reason']}")
        if cache_hits:
            print(f"cache hits: {cache_hits}/{n}")
    return {"pass": 0, "fail": 1}.get(verdict["verdict"], 2)


__all__ = ["main", "make_backend"]
