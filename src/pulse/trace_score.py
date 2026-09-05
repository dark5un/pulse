"""Shared trace scorer: single scoring path for corpus, leaderboard, gates.

Extracted from ``scripts/build_corpus.py::score_trace`` — that script now
imports from here. Output schema is unchanged (byte-identical sidecars).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .signals import extract_signals
from .signals_unroll import detect_cost, detect_latency, detect_skill_deadweight
from .unroll_loader import UnrollBundle, bundle_to_messages, load_unroll_trace


def anonymize(session_id: str) -> str:
    """sha256 hex digest of session_id, first 12 chars."""
    return hashlib.sha256(session_id.encode()).hexdigest()[:12]


def score_bundle(
    bundle: UnrollBundle,
    messages: list[dict] | None = None,
    extra_signals: list | None = None,
    deep: dict | None = None,
) -> dict:
    """Score a loaded bundle. Returns sidecar-compatible record dict.

    ``extra_signals`` (e.g. LLM-judge verdicts) are appended to the signal
    list and folded into penalty/score. ``deep`` (judge model, signal names,
    token counts) is stored verbatim — present only when provided, so the
    deterministic-only path stays byte-identical.
    """
    msgs = messages if messages is not None else bundle_to_messages(bundle)
    result = extract_signals(msgs)
    task_type = result.metrics.get("task_type", "coding")
    unroll_sigs = (
        detect_latency(bundle)
        + detect_cost(bundle, task_type)
        + detect_skill_deadweight(bundle, msgs)
    )
    all_sigs = list(result.signals) + unroll_sigs + list(extra_signals or [])
    penalty = sum(s.penalty for s in all_sigs)
    score = max(0, min(100, round(100 - penalty)))
    rec: dict = {
        "session_id": bundle.session_id,
        "model": bundle.model,
        "score": score,
        "penalty": penalty,
        "cost_usd": bundle.cost_usd,
        "task_type": task_type,
        "active_skills": list(bundle.active_skills),
        "session_tags": list(bundle.session_tags),
        "signals": [
            {
                "name": s.name,
                "severity": s.severity,
                "penalty": s.penalty,
                "label": s.label,
                "evidence": s.evidence[:2],
            }
            for s in all_sigs
        ],
    }
    if deep is not None:
        rec["deep"] = deep
    return rec


def score_trace_file(path: str | Path) -> dict:
    """Load a trace file and score it in one call. Adds ``path`` key."""
    p = Path(path)
    bundle = load_unroll_trace(str(p))
    rec = score_bundle(bundle, bundle_to_messages(bundle))
    rec["path"] = str(p)
    return rec


__all__ = ["anonymize", "score_bundle", "score_trace_file"]
