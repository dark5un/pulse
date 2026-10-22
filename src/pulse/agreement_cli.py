"""`pulse agreement` implementation: judge-vs-deterministic on a corpus.

Runs the judge over up to --limit traces (on-disk verdict cache keyed by
trace sha256 + prompt version, so reruns are free), builds comparable-pair
label lists, prints kappa + agreement + gate verdict (PASS only at
kappa >= 0.6, n >= 50).

Failure contract (M0): a judge/backend CALL failure is loud — the run exits
2 naming the failed trace; gate FAIL remains 1. The verdict cache is
flushed per record, so a rerun after a loud failure resumes from cache
(one dead endpoint at snapshot #40/50 costs 1 session, not 40).

Cache format (v2): key = sha256(trace bytes + PROMPT_VERSION)[:16]; VALUE =
{signal: finding} — finding-aware (yes|no|unscoreable), because
signal-names alone lose the abstain distinction. PROMPT_VERSION is part of
the key, so v1 list-valued entries can never collide with v2 dicts.

Polarity (ADR 0012, pinned by truth-table tests in test_agreement_polarity):
the v2 prompt defines finding="yes" as "the PROBLEM was found", and a
detector-positive row (correction_chain / premature_stop present) IS an
instance of that problem — so judge-positive (finding=yes, penalty>0)
pairs with detector-present; finding=no is judge-negative; unscoreable or
an ABSENT verdict abstains and is excluded from that pair's kappa only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .agreement import agreement_rate, cohen_kappa, gate
from .judge import JUDGE_MODEL_DEFAULT, OpenAIJudge
from .leaderboard_cli import load_corpus_records
from .signals import extract_signals
from .signals_deep import (
    PROMPT_VERSION,
    JudgeBudgetError,
    JudgeCallError,
    JudgeRun,
    resolve_prompt_budget,
    run_judge,
)
from .unroll_loader import bundle_to_messages, load_unroll_trace

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


def _det_labels(messages: list[dict]) -> dict[str, int]:
    names = {s.name for s in extract_signals(messages).signals}
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Judge-vs-deterministic agreement gate")
    ap.add_argument("--corpus", default="corpus")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--cache", default=".pulse_agreement_cache.json")
    ap.add_argument("--judge-model", default="")
    ap.add_argument("--judge-base-url", default="")
    ap.add_argument(
        "--judge-context",
        type=int,
        default=0,
        help="explicit judge context window (tokens); overrides the "
        "PULSE_JUDGE_CONTEXT env and the read-only /v1/models probe (ADR 0010)",
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    records = load_corpus_records(args.corpus)[: args.limit]
    cache_path = Path(args.cache)
    try:
        cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    except (json.JSONDecodeError, OSError):
        cache = {}
    backend = make_backend(args)
    # Decision 11 / ADR 0010: model-derived prompt budget, resolved BEFORE
    # any judge call; if no window is knowable the run refuses to start
    # (names the knobs) rather than assume one.
    try:
        budget = resolve_prompt_budget(
            backend, args.judge_context or None
        )
    except JudgeBudgetError as e:
        print(f"judge budget failure: {e}", file=sys.stderr)
        return 2
    print(
        f"judge prompt budget: {budget.budget_chars} chars "
        f"(source={budget.source}, context_window_tokens={budget.context_window_tokens})",
        file=sys.stderr,
    )
    pairs: dict[str, tuple[list[int], list[int]]] = {
        "correction_chain": ([], []),
        "premature_stop": ([], []),
    }
    abstained = {pair: 0 for pair in pairs}
    rate_pos = {sig: 0 for sig in RATE_SIGNALS}
    rate_n = {sig: 0 for sig in RATE_SIGNALS}
    n = 0
    cache_hits = 0
    runs: list[JudgeRun] = []
    for rec in records:
        path = rec.get("path", "")
        if not path or not Path(str(path)).exists():
            continue
        bundle = load_unroll_trace(str(path))
        messages = bundle_to_messages(bundle)
        key = hashlib.sha256(
            Path(str(path)).read_bytes() + PROMPT_VERSION.encode()
        ).hexdigest()[:16]
        if isinstance(cache.get(key), dict):
            findings = cache[key]
            cache_hits += 1
            jl = _labels_from_findings(findings)
        else:
            try:
                run = run_judge(messages, backend, budget=budget)
            except JudgeCallError as e:
                # Loud-failure contract (M0): name the failed trace, exit
                # nonzero; records judged so far are already flushed.
                print(f"judge call failure on trace {path}: {e}", file=sys.stderr)
                print(
                    f"verdict cache intact after {n} record(s); a rerun resumes from cache",
                    file=sys.stderr,
                )
                return 2
            for d in run.diagnostics:
                print(f"judge parse diagnostic: {d}", file=sys.stderr)
            runs.append(run)
            jl = _labels_from_findings(run.findings)
            # v2 cache VALUE is the finding map (yes|no|unscoreable) —
            # names alone would erase the abstain distinction.
            cache[key] = run.findings
            # Flush per record: an endpoint death at #40/50 must cost one
            # session, not the whole batch (UX finding, M0).
            _flush_cache(cache_path, cache)
        dl = _det_labels(messages)
        for sig in pairs:
            if jl[sig] is None:  # abstain: excluded from THIS pair's kappa only
                abstained[sig] += 1
            else:
                pairs[sig][0].append(jl[sig])  # type: ignore[arg-type]
                pairs[sig][1].append(dl[sig])
        for sig in RATE_SIGNALS:
            label = jl[f"_{sig}_rate"]
            if label is not None:
                rate_n[sig] += 1
                rate_pos[sig] += label
        n += 1
    _flush_cache(cache_path, cache)
    result: dict = {"n": n, "cache_hits": cache_hits, "pairs": {}, "abstained": abstained}
    kappas = []
    for sig, (jl_list, dl_list) in pairs.items():
        k = cohen_kappa(jl_list, dl_list)
        kappas.append(k)
        result["pairs"][sig] = {"kappa": k, **agreement_rate(jl_list, dl_list)}
    result["hallucination_judge_rate"] = (
        round(rate_pos["hallucination"] / rate_n["hallucination"], 3)
        if rate_n["hallucination"]
        else 0.0
    )
    result["context_retention_judge_rate"] = (
        round(rate_pos["context_retention"] / rate_n["context_retention"], 3)
        if rate_n["context_retention"]
        else 0.0
    )
    grounded = sum(r.grounded for r in runs)
    total_quotes = sum(r.total_quotes for r in runs)
    result["evidence_grounding"] = {
        "grounded": grounded,
        "total": total_quotes,
        "rate": round(grounded / total_quotes, 3) if total_quotes else None,
        "note": "fresh judge calls only (cache hits carry findings, not quotes)",
    }
    if runs:
        sizes = sorted(r.prompt_chars for r in runs)
        result["prompt_stats"] = {
            "fresh_calls": len(runs),
            "min_chars": sizes[0],
            "median_chars": sizes[len(sizes) // 2],
            "max_chars": sizes[-1],
            "truncated": sum(1 for r in runs if r.truncated),
        }
    worst = min(kappas) if kappas else 0.0
    result["gate"] = {"min_kappa": worst, **gate(worst, n)}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for sig, r in result["pairs"].items():
            print(
                f"{sig:<18} kappa={r['kappa']:<6} agree={r['rate']:<5} "
                f"n={r['n']} abstained={abstained[sig]}"
            )
        print(
            f"hallucination judge-rate={result['hallucination_judge_rate']} "
            f"({rate_pos['hallucination']}/{rate_n['hallucination']}) "
            f"context-retention judge-rate={result['context_retention_judge_rate']} "
            f"({rate_pos['context_retention']}/{rate_n['context_retention']}) "
            "(spot-check required, never kappa)"
        )
        pct = f" ({100.0 * grounded / total_quotes:.1f}%)" if total_quotes else ""
        print(f"evidence grounding: {grounded}/{total_quotes} quotes grounded{pct}")
        if runs:
            ps = result["prompt_stats"]
            print(
                f"prompt size (fresh calls): median={ps['median_chars']} "
                f"max={ps['max_chars']} truncated={ps['truncated']}/{ps['fresh_calls']}"
            )
        g = result["gate"]
        status = "PASS" if g["pass"] else "FAIL (pending)"
        print(f"gate: {status} min_kappa={worst} n={n} (needs kappa>=0.6, n>=50)")
        if cache_hits:
            print(f"cache hits: {cache_hits}/{n}")
    return 0 if result["gate"]["pass"] else 1


__all__ = ["main", "make_backend"]
