"""Cross-model skill portability: which skills travel, which are model lore.

Pure functions over score-record dicts — needs no Hermes install.
Rate = deadweight-flagged / times-loaded, per skill per model.
Verdicts (provisional thresholds until ~100-session calibration):
  portable — rate 0 on every model (low deadweight everywhere)
  dead — rate >= 0.5 on every model (deadweight everywhere)
  model_specific — anything in between.
"""

from __future__ import annotations

import re

# Provisional: a model counts as "deadweight" for a skill at >= 50% flag rate.
DEADWEIGHT_RATE = 0.5

_SKILL_RE = re.compile(r"[Ss]kill '([^']+)'")


def _flagged_skills(rec: dict) -> set[str]:
    flagged = set()
    for s in rec.get("signals", []):
        if not isinstance(s, dict) or s.get("name") != "skill_deadweight":
            continue
        for text in [str(s.get("label", "")), *[str(e) for e in s.get("evidence", [])]]:
            m = _SKILL_RE.search(text)
            if m:
                flagged.add(m.group(1))
                break
    return flagged


def portability(records: list[dict]) -> dict[str, dict]:
    """Return {skill: {models: {model: deadweight_rate}, verdict}}."""
    loaded: dict[str, dict[str, int]] = {}
    flagged: dict[str, dict[str, int]] = {}
    for rec in records:
        model = str(rec.get("model", "") or "?")
        for skill in rec.get("active_skills", []) or []:
            loaded.setdefault(skill, {}).setdefault(model, 0)
            loaded[skill][model] += 1
        for skill in _flagged_skills(rec):
            flagged.setdefault(skill, {}).setdefault(model, 0)
            flagged[skill][model] += 1
    out: dict[str, dict] = {}
    for skill in sorted(set(loaded) | set(flagged)):
        models: dict[str, float] = {}
        for model in sorted(set(loaded.get(skill, {})) | set(flagged.get(skill, {}))):
            n = loaded.get(skill, {}).get(model, 0)
            f = flagged.get(skill, {}).get(model, 0)
            models[model] = round(f / n, 2) if n else (1.0 if f else 0.0)
        rates = list(models.values())
        if all(r == 0.0 for r in rates):
            verdict = "portable"
        elif all(r >= DEADWEIGHT_RATE for r in rates):
            verdict = "dead"
        else:
            verdict = "model_specific"
        out[skill] = {"models": models, "verdict": verdict}
    return out


__all__ = ["DEADWEIGHT_RATE", "portability"]
