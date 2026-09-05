"""Unroll-native detectors over trace-bundle fields.

Pure functions: UnrollBundle (+ messages where needed) in, Signal list out.
Mirrors ``signals.py`` conventions (evidence quotes, penalty ceilings 0-25).

Thresholds are provisional until ~100-session calibration — never present
them as calibrated.
"""

from .constants import TASK_BRAINSTORM, TASK_CODING
from .models import Signal
from .unroll_loader import UnrollBundle

# Provisional: absolute per-step latency ceiling (ms) until corpus calibration.
LATENCY_STEP_MS = 5000

# Provisional per-task cost ceilings (USD) until 100-session calibration.
COST_CEILINGS = {
    "brainstorm": 0.50,
    "coding": 5.00,
}


def detect_latency(bundle: UnrollBundle) -> list[Signal]:
    """Flag steps whose replay cost dwarfs the original.

    v1 rule: any timeline step with ``duration_ms > 5000`` fires a warning
    with the offending duration quoted as evidence.
    """
    signals: list[Signal] = []
    for entry in bundle.timeline:
        duration = entry.get("duration_ms", 0) or 0
        if isinstance(duration, (int, float)) and duration > LATENCY_STEP_MS:
            kind = entry.get("kind", "step")
            offset = entry.get("offset_ms", "?")
            signals.append(Signal(
                name="latency_regression",
                target="agent",
                severity="warning",
                penalty=10,
                evidence=[f"{kind} took {duration}ms at offset {offset}ms"],
                label=f"Slow step: {kind} {duration}ms (>{LATENCY_STEP_MS}ms)",
            ))
    return signals


def detect_cost(bundle: UnrollBundle, task_type: str = TASK_CODING) -> list[Signal]:
    """Flag sessions whose cost_usd exceeds the task-type expectation.

    Provisional thresholds: brainstorm > $0.50, coding > $5.00.
    Unknown task types fall back to the coding ceiling.
    """
    ceiling = COST_CEILINGS.get(task_type, COST_CEILINGS["coding"])
    if bundle.cost_usd > ceiling:
        return [Signal(
            name="cost_anomaly",
            target="agent",
            severity="warning",
            penalty=10,
            evidence=[f"cost_usd=${bundle.cost_usd:.4f} for {task_type} (ceiling ${ceiling:.2f})"],
            detail="provisional threshold — pending 100-session calibration",
            label=f"Cost ${bundle.cost_usd:.4f} exceeds ${ceiling:.2f} {task_type} ceiling",
        )]
    return []


def detect_skill_deadweight(bundle: UnrollBundle, messages: list[dict]) -> list[Signal]:
    """Flag ACTIVE_SKILLS entries with no downstream use.

    Rule: skill loaded but zero tool_call steps in the timeline AND the
    session contains a correction → warning. Loaded but unused with no
    correction → info only. Brainstorm sessions downgrade warnings to info
    (exploration is expected). No skills loaded, or tools were used → none.
    """
    from .signals import CORRECTION_STARTS
    from .task_type import detect_task_type

    if not bundle.active_skills:
        return []
    if any(e.get("kind") == "tool_call" for e in bundle.timeline):
        return []
    correction_quote = ""
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        if any(content.lower().strip().startswith(w) for w in CORRECTION_STARTS):
            correction_quote = content[:120]
            break
    is_brainstorm = detect_task_type(messages) == TASK_BRAINSTORM
    signals: list[Signal] = []
    for skill in bundle.active_skills:
        if correction_quote and not is_brainstorm:
            signals.append(Signal(
                name="skill_deadweight",
                target="agent",
                severity="warning",
                penalty=8,
                evidence=[f"skill '{skill}' loaded but unused before corrections", correction_quote],
                label=f"Skill '{skill}' loaded but unused",
            ))
        else:
            signals.append(Signal(
                name="skill_deadweight",
                target="agent",
                severity="info",
                penalty=0,
                evidence=[f"skill '{skill}' loaded with no tool calls"],
                label=f"Skill '{skill}' loaded but unused",
            ))
    return signals
