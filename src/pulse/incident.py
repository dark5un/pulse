"""Incident postmortem skeleton (plan item 5 / C1): 3am speed over flags.

``pulse incident --trace T --bad-step N`` prints timeline around N, score
before/after N, and the counterfactual command to try — one command, not
four flags remembered under stress.
"""

from __future__ import annotations

from pulse.trace_score import score_bundle
from pulse.unroll_loader import bundle_to_messages, load_unroll_trace


def skeleton(trace: str, bad_step: int, window: int = 3) -> dict:
    """Structured postmortem: window around N, scores split at N, next step."""
    bundle = load_unroll_trace(trace)
    n = len(bundle.timeline)
    if bad_step < 0 or bad_step >= n:
        raise ValueError(f"bad_step {bad_step} out of range (0..{n - 1})")
    lo = max(0, bad_step - window)
    hi = min(n, bad_step + window + 1)
    msgs = bundle_to_messages(bundle)
    full = score_bundle(bundle, msgs)
    # Score halves: timeline halves mapped back through bundle_to_messages
    # shape is best-effort — halves with no user message score 100 by guard.
    from pulse.unroll_loader import UnrollBundle

    def _score_half(entries: list[dict]) -> int:
        half = UnrollBundle(
            session_id=bundle.session_id, model=bundle.model,
            timeline=entries, cost_usd=bundle.cost_usd,
        )
        return int(score_bundle(half, bundle_to_messages(half))["score"])

    stem = trace.rsplit("/", 1)[-1]
    return {
        "trace": stem,
        "bad_step": bad_step,
        "timeline_window": bundle.timeline[lo:hi],
        "window_range": [lo, hi - 1],
        "score_before": _score_half(bundle.timeline[:bad_step]),
        "score_after": _score_half(bundle.timeline[bad_step:]),
        "score_full": full["score"],
        "counterfactual": [
            f"python {stem} --substitute-tool='{bad_step} {{\"args\": ...}}'",
            f"python {stem} --from={lo} --to={hi - 1} --show-state",
        ],
    }


def render(skel: dict) -> str:
    lines = [
        (
            f"incident: {skel['trace']} step {skel['bad_step']} "
            f"(window {skel['window_range'][0]}..{skel['window_range'][1]})"
        ),
        (
            f"score before={skel['score_before']} after={skel['score_after']} "
            f"full={skel['score_full']}"
        ),
        "timeline:",
    ]
    base = skel["window_range"][0]
    for i, entry in enumerate(skel["timeline_window"]):
        mark = ">>>" if base + i == skel["bad_step"] else "   "
        kind = entry.get("kind", "?")
        extra = " ".join(
            f"{k}={entry[k]}" for k in ("name", "duration_ms", "offset_ms") if k in entry
        )
        lines.append(f"  {mark} [{base + i}] {kind} {extra}".rstrip())
    lines.append("counterfactual:")
    lines.extend(f"  {c}" for c in skel["counterfactual"])
    return "\n".join(lines)


__all__ = ["render", "skeleton"]
