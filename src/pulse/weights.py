"""Validated, atomic learned weights persistence."""
from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .paths import weights_file

DEFAULT_WEIGHTS: dict[str, dict[str, Any]] = {
    name: {"penalty": penalty, "useful": 0, "not_useful": 0}
    for name, penalty in {"correction_chain":12,"frustration":12,"goal_drift":6,"vague_prompts":10,"shrinking_prompts":5,"reasoning_loop":15,"premature_stop":10,"tool_error":8,"tool_repetition":10,"shallow_read":12,"low_diversity":5,"goal_completion":10,"context_retention":10,"correction_quality":8,"hallucination":15}.items()
}

#: Signal names ever recognized (current defaults + retired keys dropped
#: silently on save, never crashed on).
KNOWN_SIGNAL_NAMES = frozenset(DEFAULT_WEIGHTS) | {"deep_context_drift"}
_feedback_count = 0

def _valid_entry(value: object) -> bool:
    if not isinstance(value, dict): return False
    penalty = value.get("penalty")
    return isinstance(penalty, (int, float)) and not isinstance(penalty, bool) and penalty >= 0 and isinstance(value.get("useful", 0), int) and isinstance(value.get("not_useful", 0), int)

def load(path: Path | None = None) -> dict[str, Any]:
    global _feedback_count
    result: dict[str, Any] = copy.deepcopy(DEFAULT_WEIGHTS)
    target = path or weights_file()
    try: data: object = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError): data = {}
    _feedback_count = 0
    if isinstance(data, dict):
        meta = data.get("_meta")
        if isinstance(meta, dict) and isinstance(meta.get("total_feedback"), int) and meta["total_feedback"] >= 0:
            _feedback_count = meta["total_feedback"]
            result["_meta"] = {"total_feedback": _feedback_count}
        for name, value in data.items():
            if name != "_meta" and _valid_entry(value):
                assert isinstance(value, dict)
                result[name] = {"penalty": float(value["penalty"]), "useful": value.get("useful", 0), "not_useful": value.get("not_useful", 0)}
    return result

def save(weights: dict[str, Any], path: Path | None = None) -> None:
    target = path or weights_file(); target.parent.mkdir(parents=True, exist_ok=True)
    payload = load(path)
    for name, value in weights.items():
        if name != "_meta" and _valid_entry(value): payload[name] = value
    # Drop unknown/retired keys (e.g. deep_context_drift) so stale entries
    # disappear on the next feedback write instead of being rewritten forever.
    for name in list(payload):
        if name != "_meta" and name not in DEFAULT_WEIGHTS:
            del payload[name]
    meta = weights.get("_meta", {})
    total = meta.get("total_feedback", 0) if isinstance(meta, dict) else 0
    payload["_meta"] = {"total_feedback": int(total) if isinstance(total, int) and total >= 0 else 0}
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2); stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def apply(weights: dict[str, Any], signal_name: str, default_penalty: float) -> float:
    entry = weights.get(signal_name)
    value = entry.get("penalty", default_penalty) if isinstance(entry, dict) else default_penalty
    try: numeric = float(value)
    except (TypeError, ValueError): return default_penalty
    return round(max(default_penalty * .5, min(default_penalty * 1.5, numeric)), 1)

def record_feedback(weights: dict[str, Any], signal_name: str, useful: bool) -> dict[str, Any]:
    global _feedback_count
    entry = weights.get(signal_name)
    if not _valid_entry(entry): return weights
    assert isinstance(entry, dict)
    meta = weights.setdefault("_meta", {"total_feedback": 0})
    if not isinstance(meta, dict): meta = weights["_meta"] = {"total_feedback": 0}
    meta["total_feedback"] = int(meta.get("total_feedback", 0)) + 1
    _feedback_count = meta["total_feedback"]
    key = "useful" if useful else "not_useful"; entry[key] = entry.get(key, 0) + 1
    total = entry["useful"] + entry["not_useful"]
    if meta["total_feedback"] > 5 and total >= 3:
        ratio = entry["useful"] / total
        if ratio >= .7: entry["penalty"] = round(float(entry["penalty"]) * 1.1, 1)
        elif ratio <= .4: entry["penalty"] = round(float(entry["penalty"]) * .85, 1)
    return weights

def get_feedback_count() -> int: return _feedback_count

# Compatibility for consumers that imported the old constant; runtime code resolves dynamically.
WEIGHTS_PATH = weights_file()
