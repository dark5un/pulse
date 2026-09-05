"""LLM-judge detectors (B2): goal_completion, context_retention,
correction_quality, hallucination. One combined temperature-0 call;
verdicts map to normal Signals (penalty ceiling 25, evidence quotes).
Unparseable output -> [] (never fabricate). PROMPT_VERSION pinned."""

from __future__ import annotations

import json

from pulse.judge import JudgeBackend
from pulse.models import Signal

PROMPT_VERSION = "v1"

DEEP_SIGNALS = (
    "goal_completion",
    "context_retention",
    "correction_quality",
    "hallucination",
)

# correction_quality describes the USER's correction specificity -> user target; rest agent.
TARGETS = {
    "correction_quality": "user",
    "goal_completion": "agent",
    "context_retention": "agent",
    "hallucination": "agent",
}


def build_prompt(messages: list[dict]) -> str:
    lines = [f"{m.get('role', '?')}: {str(m.get('content', ''))[:500]}" for m in messages]
    schema = (
        '{"prompt_version": "v1", "verdicts": [{"signal": "<one of '
        + "|".join(DEEP_SIGNALS)
        + '>", "finding": "yes|no", "penalty": <0-25>, "evidence": "<quote>"}]}'
    )
    return (
        "You are Pulse, a session-quality judge. Verdicts ONLY on the four signals; "
        "'yes' means the PROBLEM was found (penalty > 0 needs evidence quote). "
        f"Reply with exactly this JSON shape: {schema}\n\nTRANSCRIPT:\n" + "\n".join(lines)
    )


def detect_deep(messages: list[dict], backend: JudgeBackend) -> list[Signal]:
    try:
        payload = json.loads(backend.judge(build_prompt(messages)).text)
    except Exception:  # noqa: BLE001 — judge/network/parse failure reads as no verdicts
        return []
    if not isinstance(payload, dict) or payload.get("prompt_version") != PROMPT_VERSION:
        return []
    verdicts = payload.get("verdicts", [])
    if not isinstance(verdicts, list):
        return []
    signals: list[Signal] = []
    for v in verdicts:
        if not isinstance(v, dict) or v.get("signal") not in DEEP_SIGNALS:
            continue
        try:
            penalty = max(0.0, min(25.0, float(v.get("penalty", 0))))
        except (TypeError, ValueError):
            continue
        signals.append(
            Signal(
                name=str(v["signal"]),
                target=TARGETS[str(v["signal"])],
                severity=(
                    "info" if penalty == 0 else ("warning" if penalty <= 10 else "critical")
                ),
                penalty=penalty,
                evidence=[str(v.get("evidence", ""))[:200]],
                detail="llm-judge " + PROMPT_VERSION + " — provisional until agreement-gated",
                label=f"Judge: {v.get('finding', '?')} — {v['signal']}",
            )
        )
    return signals


__all__ = ["DEEP_SIGNALS", "PROMPT_VERSION", "build_prompt", "detect_deep"]
