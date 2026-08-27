"""Self-learning weights for Pulse signal detectors.

Stores per-signal Bayesian weights in ~/.hermes/pulse_weights.json.
Each signal's penalty weight is tuned by user feedback.
"""

import json
from pathlib import Path

WEIGHTS_PATH = Path.home() / ".hermes" / "pulse_weights.json"

DEFAULT_WEIGHTS = {
    "correction_chain": {"penalty": 12, "useful": 0, "not_useful": 0},
    "frustration": {"penalty": 12, "useful": 0, "not_useful": 0},
    "goal_drift": {"penalty": 6, "useful": 0, "not_useful": 0},
    "vague_prompts": {"penalty": 10, "useful": 0, "not_useful": 0},
    "shrinking_prompts": {"penalty": 5, "useful": 0, "not_useful": 0},
    "reasoning_loop": {"penalty": 15, "useful": 0, "not_useful": 0},
    "premature_stop": {"penalty": 10, "useful": 0, "not_useful": 0},
    "tool_error": {"penalty": 8, "useful": 0, "not_useful": 0},
    "tool_repetition": {"penalty": 10, "useful": 0, "not_useful": 0},
    "shallow_read": {"penalty": 12, "useful": 0, "not_useful": 0},
    "low_diversity": {"penalty": 5, "useful": 0, "not_useful": 0},
    "deep_context_drift": {"penalty": 5, "useful": 0, "not_useful": 0},
}

_feedback_count = 0


def load() -> dict:
    """Load weights from file, merging with defaults for any new signals."""
    if WEIGHTS_PATH.exists():
        try:
            data = json.loads(WEIGHTS_PATH.read_text())
            merged = dict(DEFAULT_WEIGHTS)
            merged.update(data)
            # Track feedback count from meta
            global _feedback_count
            _feedback_count = merged.get("_meta", {}).get("total_feedback", 0)
            return merged
        except (json.JSONDecodeError, KeyError):
            pass
    return dict(DEFAULT_WEIGHTS)


def save(weights: dict):
    """Save weights to file."""
    WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Ensure meta exists
    if "_meta" not in weights:
        weights["_meta"] = {"total_feedback": 0}
    WEIGHTS_PATH.write_text(json.dumps(weights, indent=2))


def apply(weights: dict, signal_name: str, default_penalty: float) -> float:
    """Apply learned weight to a signal's penalty, clamped to ±50% of default."""
    w = weights.get(signal_name)
    if w is None:
        return default_penalty
    min_p = default_penalty * 0.5
    max_p = default_penalty * 1.5
    return round(max(min_p, min(max_p, w["penalty"])), 1)


def record_feedback(weights: dict, signal_name: str, useful: bool) -> dict:
    """Record a single feedback event and update the signal's weight.

    Bayesian-inspired: if >70% of feedback is useful, increase weight.
    If <40% is useful, decrease weight. Cold-start: first 5 feedback
    events don't change weights.
    """
    w = weights.get(signal_name)
    if w is None:
        return weights

    # Ensure meta
    meta = weights.setdefault("_meta", {"total_feedback": 0})
    meta["total_feedback"] = meta.get("total_feedback", 0) + 1

    # Cold start: first 5 feedback events ignored
    if meta["total_feedback"] <= 5:
        if useful:
            w["useful"] = w.get("useful", 0) + 1
        else:
            w["not_useful"] = w.get("not_useful", 0) + 1
        return weights

    if useful:
        w["useful"] = w.get("useful", 0) + 1
    else:
        w["not_useful"] = w.get("not_useful", 0) + 1

    total = w["useful"] + w["not_useful"]
    if total < 3:
        return weights  # not enough data

    ratio = w["useful"] / total
    if ratio >= 0.7:
        w["penalty"] = round(w["penalty"] * 1.1, 1)
    elif ratio <= 0.4:
        w["penalty"] = round(w["penalty"] * 0.85, 1)

    return weights


def get_feedback_count() -> int:
    return _feedback_count