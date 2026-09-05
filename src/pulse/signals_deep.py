"""LLM-judge detectors (B2): goal_completion, context_retention,
correction_quality, hallucination. One combined temperature-0 call;
verdicts map to normal Signals (penalty ceiling 25, evidence quotes).
Unparseable output -> [] (never fabricate). PROMPT_VERSION pinned."""

from __future__ import annotations

import json
import math

from .judge import JudgeBackend
from .models import Signal

PROMPT_VERSION = "v1"

#: Hard bound on judge prompt size (transcript far over budget is cut,
#: and the cut is disclosed in the prompt).
MAX_PROMPT_CHARS = 12_000
#: Per-message cap inside the prompt.
MAX_MESSAGE_CHARS = 500

DEEP_SIGNALS = (
    "goal_completion",
    "context_retention",
    "correction_quality",
    "hallucination",
)

#: Verdict findings the judge may return. Anything else is dropped.
FINDINGS = ("yes", "no")

#: Absolute penalty ceiling per verdict.
MAX_VERDICT_PENALTY = 25.0
#: Max evidence strings accepted per verdict; each capped at this length.
MAX_EVIDENCE_ITEMS = 4
MAX_EVIDENCE_CHARS = 200

# correction_quality describes the USER's correction specificity -> user target; rest agent.
TARGETS = {
    "correction_quality": "user",
    "goal_completion": "agent",
    "context_retention": "agent",
    "hallucination": "agent",
}


class VerdictParseResult:
    """parse_verdict_text outcome: accepted signals + per-verdict diagnostics."""

    def __init__(self, signals: list[Signal], diagnostics: list[str]) -> None:
        self.signals = signals
        self.diagnostics = diagnostics

    def __iter__(self):  # unpack as (signals, diagnostics)
        yield self.signals
        yield self.diagnostics


def build_prompt(messages: list[dict]) -> str:
    redacted_lines = []
    for m in messages:
        text = redact_text(str(m.get("content", ""))[:MAX_MESSAGE_CHARS])
        redacted_lines.append(f"{m.get('role', '?')}: {text}")
    schema = (
        '{"prompt_version": "v1", "verdicts": [{"signal": "<one of '
        + "|".join(DEEP_SIGNALS)
        + '>", "finding": "yes|no", "penalty": <0-25>, "evidence": "<quote>"}]}'
    )
    head = (
        "You are Pulse, a session-quality judge. Verdicts ONLY on the four signals; "
        "'yes' means the PROBLEM was found (penalty > 0 needs evidence quote). "
        f"Reply with exactly this JSON shape: {schema}\n\nTRANSCRIPT:\n"
    )
    body = "\n".join(redacted_lines)
    # Bound the transcript: cut from the middle (keep opening + recent tail),
    # and disclose the cut so the judge knows it sees a window.
    budget = MAX_PROMPT_CHARS - len(head)
    if len(body) > budget:
        keep_head = budget * 2 // 3
        keep_tail = budget - keep_head - 60
        body = (
            body[:keep_head]
            + "\n[…transcript truncated: middle omitted…]\n"
            + body[len(body) - keep_tail:]
        )
    return head + body


def redact_text(text: str) -> str:
    """Redact secrets from judge-bound text (keys, tokens, emails)."""
    import re

    patterns = [
        r"sk-(?:proj-)?[A-Za-z0-9_-]{8,}",
        r"\bgh[pousr]_[A-Za-z0-9]{8,}\b",
        r"Bearer\s+[A-Za-z0-9\-._~+/=]{8,}",
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        r"(?i)\b((?:api[_-]?key|secret|token|password)\b[^A-Za-z0-9]{0,10})([0-9a-f]{32,})\b",
    ]
    out = text
    for pat in patterns:
        out = re.sub(pat, "[REDACTED]", out)
    return out


def detect_deep(messages: list[dict], backend: JudgeBackend) -> list[Signal]:
    try:
        text = backend.judge(build_prompt(messages)).text
    except Exception:  # noqa: BLE001 — judge/network failure reads as no verdicts
        return []
    return parse_verdict_text(text).signals


def _validate_evidence(raw: object) -> list[str] | None:
    """Normalize evidence to a bounded list of bounded strings. None if invalid."""
    if isinstance(raw, str):
        items = [raw] if raw else []
    elif isinstance(raw, list):
        items = raw
    else:
        return None
    if len(items) > MAX_EVIDENCE_ITEMS:
        return None
    clean: list[str] = []
    for item in items:
        if not isinstance(item, str):
            return None
        if len(item) > MAX_EVIDENCE_CHARS * 10:
            return None
        clean.append(item[:MAX_EVIDENCE_CHARS])
    return clean


def parse_verdict_text(text: str) -> VerdictParseResult:
    """Parse a judge JSON payload into signals + diagnostics.

    Invalid verdicts (bad finding, non-finite penalty, penalty without
    evidence, bad evidence shape) are dropped with a diagnostic — they can
    never carry a penalty into scoring. Duplicate signal names merge
    deterministically (highest penalty wins).
    """
    signals: list[Signal] = []
    diagnostics: list[str] = []
    try:
        payload = json.loads(text)
    except Exception:  # noqa: BLE001 — malformed judge output reads as no verdicts
        return VerdictParseResult([], ["payload is not valid JSON"])
    if not isinstance(payload, dict) or payload.get("prompt_version") != PROMPT_VERSION:
        return VerdictParseResult([], ["payload missing or mismatched prompt_version"])
    verdicts = payload.get("verdicts", [])
    if not isinstance(verdicts, list):
        return VerdictParseResult([], ["verdicts is not a list"])
    merged: dict[str, dict] = {}
    for i, v in enumerate(verdicts):
        where = f"verdict[{i}]"
        if not isinstance(v, dict) or v.get("signal") not in DEEP_SIGNALS:
            diagnostics.append(f"{where}: unknown or missing signal")
            continue
        name = str(v["signal"])
        finding = v.get("finding", "?")
        if finding not in FINDINGS:
            diagnostics.append(f"{where} {name}: finding {finding!r} not in {list(FINDINGS)} — dropped")
            continue
        try:
            penalty = float(v.get("penalty", 0))
        except (TypeError, ValueError):
            diagnostics.append(f"{where} {name}: penalty not numeric — dropped")
            continue
        if not math.isfinite(penalty):
            diagnostics.append(f"{where} {name}: penalty {penalty!r} not finite — dropped")
            continue
        penalty = max(0.0, min(MAX_VERDICT_PENALTY, penalty))
        if finding == "no" and penalty != 0:
            diagnostics.append(f"{where} {name}: finding=no with penalty {penalty} — dropped")
            continue
        evidence = _validate_evidence(v.get("evidence", ""))
        if evidence is None:
            diagnostics.append(f"{where} {name}: evidence wrong shape or oversized — dropped")
            continue
        if penalty > 0 and not any(e.strip() for e in evidence):
            diagnostics.append(f"{where} {name}: penalty {penalty} with empty evidence — dropped")
            continue
        if name in merged:
            diagnostics.append(f"{where} {name}: duplicate signal — keeping highest penalty")
            if penalty > merged[name]["penalty"]:
                merged[name] = {"penalty": penalty, "evidence": evidence, "finding": finding}
        else:
            merged[name] = {"penalty": penalty, "evidence": evidence, "finding": finding}
    for name, m in merged.items():
        penalty = m["penalty"]
        signals.append(
            Signal(
                name=name,
                target=TARGETS[name],
                severity=(
                    "info" if penalty == 0 else ("warning" if penalty <= 10 else "critical")
                ),
                penalty=penalty,
                evidence=m["evidence"],
                detail="llm-judge " + PROMPT_VERSION + " — provisional until agreement-gated",
                label=f"Judge: {m['finding']} — {name}",
            )
        )
    return VerdictParseResult(signals, diagnostics)


__all__ = ["DEEP_SIGNALS", "PROMPT_VERSION", "VerdictParseResult", "build_prompt", "detect_deep", "parse_verdict_text"]
