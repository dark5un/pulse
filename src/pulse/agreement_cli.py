"""`pulse agreement` implementation: judge-vs-deterministic on a corpus.

Runs the judge over up to --limit traces (on-disk verdict cache keyed by
trace sha256 + prompt version, so reruns are free), builds comparable-pair
label lists, prints kappa + agreement + gate verdict (PASS only at
kappa >= 0.6, n >= 50).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .agreement import agreement_rate, cohen_kappa, gate
from .judge import JUDGE_MODEL_DEFAULT, OpenAIJudge
from .leaderboard_cli import load_corpus_records
from .signals import extract_signals
from .signals_deep import PROMPT_VERSION, detect_deep
from .unroll_loader import bundle_to_messages, load_unroll_trace


def make_backend(args):
    return OpenAIJudge(
        model=args.judge_model or JUDGE_MODEL_DEFAULT, base_url=args.judge_base_url
    )


def _det_labels(messages: list[dict]) -> dict[str, int]:
    names = {s.name for s in extract_signals(messages).signals}
    return {
        "correction_chain": 1 if "correction_chain" in names else 0,
        "premature_stop": 1 if "premature_stop" in names else 0,
    }


def _judge_labels(messages: list[dict], backend) -> dict[str, int]:
    verdicts = {s.name: s for s in detect_deep(messages, backend)}
    out = {}
    cq = verdicts.get("correction_quality")
    out["correction_chain"] = 1 if (cq and cq.penalty > 0) else 0
    gc = verdicts.get("goal_completion")
    out["premature_stop"] = 1 if (gc and gc.penalty > 0) else 0
    hall = verdicts.get("hallucination")
    ctx = verdicts.get("context_retention")
    out["_hallucination_rate"] = 1 if (hall and hall.penalty > 0) else 0
    out["_context_retention_rate"] = 1 if (ctx and ctx.penalty > 0) else 0
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Judge-vs-deterministic agreement gate")
    ap.add_argument("--corpus", default="corpus")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--cache", default=".pulse_agreement_cache.json")
    ap.add_argument("--judge-model", default="")
    ap.add_argument("--judge-base-url", default="")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    records = load_corpus_records(args.corpus)[: args.limit]
    cache_path = Path(args.cache)
    try:
        cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    except (json.JSONDecodeError, OSError):
        cache = {}
    backend = make_backend(args)
    pairs: dict[str, tuple[list[int], list[int]]] = {
        "correction_chain": ([], []),
        "premature_stop": ([], []),
    }
    hall_pos = ctx_pos = n = 0
    cache_hits = 0
    for rec in records:
        path = rec.get("path", "")
        if not path or not Path(str(path)).exists():
            continue
        bundle = load_unroll_trace(str(path))
        messages = bundle_to_messages(bundle)
        key = hashlib.sha256(
            Path(str(path)).read_bytes() + PROMPT_VERSION.encode()
        ).hexdigest()[:16]
        if key in cache:
            judge_names = cache[key]
            cache_hits += 1
            jl = {
                "correction_chain": 1 if "correction_quality" in judge_names else 0,
                "premature_stop": 1 if "goal_completion" in judge_names else 0,
                "_hallucination_rate": 1 if "hallucination" in judge_names else 0,
                "_context_retention_rate": (
                    1 if "context_retention" in judge_names else 0
                ),
            }
        else:
            jl = _judge_labels(messages, backend)
            cache[key] = [
                s
                for s in (
                    "correction_quality" if jl["correction_chain"] else None,
                    "goal_completion" if jl["premature_stop"] else None,
                    "hallucination" if jl["_hallucination_rate"] else None,
                    "context_retention" if jl["_context_retention_rate"] else None,
                )
                if s
            ]
        dl = _det_labels(messages)
        for sig in pairs:
            pairs[sig][0].append(jl[sig])
            pairs[sig][1].append(dl[sig])
        hall_pos += jl["_hallucination_rate"]
        ctx_pos += jl["_context_retention_rate"]
        n += 1
    try:
        cache_path.write_text(json.dumps(cache, indent=2))
    except OSError as e:
        print(f"warning: could not write cache: {e}")
    result: dict = {"n": n, "cache_hits": cache_hits, "pairs": {}}
    kappas = []
    for sig, (jl_list, dl_list) in pairs.items():
        k = cohen_kappa(jl_list, dl_list)
        kappas.append(k)
        result["pairs"][sig] = {"kappa": k, **agreement_rate(jl_list, dl_list)}
    result["hallucination_judge_rate"] = round(hall_pos / n, 3) if n else 0.0
    result["context_retention_judge_rate"] = round(ctx_pos / n, 3) if n else 0.0
    worst = min(kappas) if kappas else 0.0
    result["gate"] = {"min_kappa": worst, **gate(worst, n)}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for sig, r in result["pairs"].items():
            print(f"{sig:<18} kappa={r['kappa']:<6} agree={r['rate']:<5} n={r['n']}")
        print(
            f"hallucination judge-rate={result['hallucination_judge_rate']} "
            f"context-retention judge-rate={result['context_retention_judge_rate']} "
            "(spot-check required, never kappa)"
        )
        g = result["gate"]
        status = "PASS" if g["pass"] else "FAIL (pending)"
        print(f"gate: {status} min_kappa={worst} n={n} (needs kappa>=0.6, n>=50)")
        if cache_hits:
            print(f"cache hits: {cache_hits}/{n}")
    return 0 if result["gate"]["pass"] else 1


__all__ = ["main", "make_backend"]
