"""Deterministic signal extraction from conversation messages.

Every function in this module is a pure function: messages in,
signal list out. No side effects, no state.
"""

import json
import re
from collections import Counter

from pulse.constants import (
    NON_ANALYTICAL,
    READ_TOOLS,
    TASK_BRAINSTORM,
    TASK_CODING,
    TASK_WRITING,
    WRITE_TOOLS,
)
from pulse.models import RuntimeLog, Signal, SignalResult
from pulse.task_type import detect_task_type

# ── Keyword sets (litmus-tested against known transcripts) ─────────────────

CORRECTION_STARTS: set[str] = {
    "no", "wrong", "that's not", "i meant", "not that",
    "revert", "undo", "that's not right",
}

FRUSTRATION_KW: set[str] = {
    "lazy", "sloppy", "you're not listening",
    "ignoring", "are you kidding", "are you serious",
    "read the file", "did you even read",
}

REASONING_LOOP_KW: set[str] = {
    "oh wait", "let me reconsider",
    "hmm, actually", "let me think about this again",
    "no wait",
}

PREMISE_STOP_KW: set[str] = {
    "should i continue", "want me to keep going",
    "good stopping point", "natural checkpoint",
    "continue in a new session", "known limitation",
}

GOAL_DRIFT_KW: set[str] = {
    "scrap that", "let me start over",
}


# ── Minimum session guard ──────────────────────────────────────────────────

def _check_minimum_messages(messages: list[dict]) -> str | None:
    """Return a skip reason if the session is too short, else None.

    Checks total message count, not user turns — supports continuations
    where the user may send only 1-2 new prompts in an existing session.
    """
    total_msgs = len(messages)
    if total_msgs < 5:
        return "insufficient_data"
    return None


# ── Correction chain ──────────────────────────────────────────────────────

def _detect_correction_chain(messages: list[dict], task_type: str) -> list[Signal]:
    """Detect 3+ consecutive user turns starting with a correction word.

    Litmus: 3x "no, that's wrong" in a row → fires.
            Single "no, do X instead" → does not fire.
            "no" mid-sentence → does not fire.
            Brainstorm session → does not fire.
    """
    if task_type == TASK_BRAINSTORM:
        return []

    signals: list[Signal] = []
    chain_len = 0
    chain_turns: list[int] = []

    for idx, msg in enumerate(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        stripped = content.lower().strip()
        is_correction = any(
            stripped.startswith(w) for w in CORRECTION_STARTS
        )
        if is_correction:
            chain_len += 1
            chain_turns.append(idx)
        else:
            if chain_len >= 3:
                evidence = [
                    messages[t].get("content", "")
                    for t in chain_turns[-3:]
                ]
                signals.append(Signal(
                    name="correction_chain",
                    target="user",
                    severity="warning",
                    penalty=12,
                    evidence=evidence,
                    label=f"{chain_len} consecutive correction turns",
                ))
            chain_len = 0
            chain_turns = []

    # Check if chain ended at last turn
    if chain_len >= 3:
        evidence = [
            messages[t].get("content", "")
            for t in chain_turns[-3:]
        ]
        signals.append(Signal(
            name="correction_chain",
            target="user",
            severity="warning",
            penalty=12,
            evidence=evidence,
            label=f"{chain_len} consecutive correction turns",
        ))

    return signals


# ── Frustration ───────────────────────────────────────────────────────────

def _detect_frustration(messages: list[dict], task_type: str) -> list[Signal]:
    """Detect frustration keywords in user turns.

    Litmus: "stop, this is wrong again" + "you're not listening either" → fires.
            "this is not correct, use library X" → does not fire.
            Single "wrong" in a long calm message → does not fire.
            System messages (context compaction) are excluded.
    """
    signals: list[Signal] = []
    frustration_turns: list[int] = []

    for idx, msg in enumerate(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        # Skip Hermes system messages
        if content.startswith(("[CONTEXT COMPACTION", "[SYSTEM")):
            continue
        lower = content.lower()
        hits = sum(1 for kw in FRUSTRATION_KW if kw in lower)
        if hits > 0:
            frustration_turns.append(idx)

    if len(frustration_turns) >= 2:
        evidence = [
            messages[t].get("content", "")[:120]
            for t in frustration_turns[-2:]
        ]
        signals.append(Signal(
            name="frustration",
            target="user",
            severity="warning",
            penalty=12,
            evidence=evidence,
            label=f"Frustration signals in {len(frustration_turns)} turns",
        ))

    return signals


# ── Goal drift ────────────────────────────────────────────────────────────

def _detect_goal_drift(messages: list[dict], task_type: str) -> list[Signal]:
    """Detect goal direction changes.

    Only fires in coding/writing sessions, not brainstorm or research.
    """
    if task_type in NON_ANALYTICAL:
        return []

    signals: list[Signal] = []
    drift_turns: list[int] = []

    for idx, msg in enumerate(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        lower = content.lower()
        hits = sum(1 for kw in GOAL_DRIFT_KW if kw in lower)
        if hits > 0:
            drift_turns.append(idx)

    if drift_turns:
        evidence = [
            messages[t].get("content", "")
            for t in drift_turns[-2:]
        ]
        signals.append(Signal(
            name="goal_drift",
            target="user",
            severity="info",
            penalty=6,
            evidence=evidence,
            label=f"Goal changed {len(drift_turns)} times",
        ))

    return signals


# ── Prompt specificity ──────────────────────────────────────────────────

TECH_TERMS = r"\b(python|js|ts|rust|go|api|db|sql|http|json|yaml|toml|css|react|docker|git|ssh|port|config|env|aws|gcp|azure|linux|macos|windows)\b"


def _prompt_specificity_score(text: str) -> float:
    """Score a single prompt for specificity (0–100).

    Factors: length, file paths, numbers, tech terms, structure (bullets).
    Only penalises when all factors are absent (vague).
    """
    fp = len(re.findall(r"[\w./-]+\.\w{2,4}", text))
    num = len(re.findall(r"\b\d+\b", text))
    tech = len(re.findall(TECH_TERMS, text.lower()))
    bullets = text.count("\n- ") + text.count("\n* ")
    constraints = fp + num + tech + bullets

    score = (
        min(len(text) / 40, 1.0) * 10
        + min(constraints / 3, 1.0) * 50
        + bullets * 10
        + fp * 20
    )
    return min(100.0, score)


def _detect_vague_prompts(messages: list[dict], task_type: str) -> list[Signal]:
    """Detect persistently vague prompting.

    Only fires on coding/writing tasks with <30 avg specificity.
    Does NOT fire on chat or brainstorm sessions.
    Does NOT fire when the single prompt has file path terms regardless of length.
    """
    if task_type not in (TASK_CODING, TASK_WRITING):
        return []

    user_texts = [
        m.get("content", "")
        for m in messages
        if m.get("role") == "user" and m.get("content")
    ]
    if not user_texts:
        return []

    scores = [_prompt_specificity_score(t) for t in user_texts]
    avg = sum(scores) / len(scores)

    if avg >= 30:
        return []

    signals: list[Signal] = []
    evidence = [user_texts[0][:80], user_texts[-1][:80]]
    signals.append(Signal(
        name="vague_prompts",
        target="user",
        severity="info",
        penalty=10,
        evidence=evidence,
        label=f"Prompts avg {avg:.0f}/100 specificity (below 30)",
    ))
    return signals


# ── Reasoning loop ───────────────────────────────────────────────────────

def _detect_reasoning_loops(messages: list[dict], task_type: str) -> list[Signal]:
    """Detect agent self-correcting in place.

    Does not fire on brainstorm sessions where reflective language is natural.

    Litmus: 3+ "oh wait / actually / let me reconsider" in one turn → fires.
            Single "actually, the answer is 42" → does not fire.
    """
    if task_type == TASK_BRAINSTORM:
        return []
    signals: list[Signal] = []

    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        lower = content.lower()
        hits = sum(1 for kw in REASONING_LOOP_KW if kw in lower)
        if hits >= 2:
            signals.append(Signal(
                name="reasoning_loop",
                target="agent",
                severity="warning",
                penalty=15,
                evidence=[content[:200]],
                label=f"Agent self-correcting in place ({hits}x in one turn)",
            ))

    return signals


# ── Premature stopping ───────────────────────────────────────────────────

def _detect_premature_stop(messages: list[dict], task_type: str) -> list[Signal]:
    """Detect agent asking to stop mid-task.

    Does not fire on brainstorm or research sessions,
    where reflective language is natural.
    """
    if task_type in NON_ANALYTICAL:
        return []

    signals: list[Signal] = []

    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        lower = content.lower()
        hits = sum(1 for kw in PREMISE_STOP_KW if kw in lower)
        if hits > 0:
            signals.append(Signal(
                name="premature_stop",
                target="agent",
                severity="warning",
                penalty=10,
                evidence=[content[:200]],
                label="Agent asking to stop mid-task",
            ))

    return signals


# ── Tool repetition ──────────────────────────────────────────────────────

def _detect_tool_repetition(messages: list[dict], task_type: str) -> list[Signal]:
    """Detect same tool called 4+ times in the last 10 calls.

    Only considers coding-relevant tools (reads, writes, terminal).
    Does not fire on brainstorm/research where web_search repetition is normal.
    """
    if task_type in NON_ANALYTICAL:
        return []

    REPETITION_TOOLS = READ_TOOLS | WRITE_TOOLS | {"terminal", "execute_code"}

    tool_sequence: list[str] = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        tcs = msg.get("tool_calls") or []
        if isinstance(tcs, dict):
            tcs = [tcs]
        for tc in tcs:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function", tc)
            name = fn.get("name", "") if isinstance(fn, dict) else ""
            if name and name in REPETITION_TOOLS:
                tool_sequence.append(name)

    if len(tool_sequence) < 4:
        return []

    win_size = min(10, len(tool_sequence))
    recent = tool_sequence[-win_size:]
    counts = Counter(recent)

    signals: list[Signal] = []
    for tool, count in counts.most_common():
        if count >= 4 and count > len(recent) * 0.4:
            signals.append(Signal(
                name="tool_repetition",
                target="agent",
                severity="warning",
                penalty=10,
                evidence=[f"{tool} called {count}x in last {win_size} tool calls"],
                label=f"{tool} called {count}x in recent {win_size} tool calls",
            ))
            break

    return signals


# ── Read:Edit ratio ───────────────────────────────────────────────────────

def _detect_read_edit_ratio(messages: list[dict], task_type: str) -> list[Signal]:
    """Detect shallow (low) Read:Edit ratio.

    Only fires on coding sessions where research depth is meaningful.
    Brainstorm, research, and writing sessions naturally have low Read:Edit.
    """
    if task_type != TASK_CODING:
        return []
    reads = 0
    edits = 0
    for msg in messages:
        tcs = msg.get("tool_calls") or []
        if isinstance(tcs, dict):
            tcs = [tcs]
        for tc in tcs:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function", tc)
            name = fn.get("name", "") if isinstance(fn, dict) else ""
            if not name:
                continue
            if name in READ_TOOLS:
                reads += 1
            if name in WRITE_TOOLS:
                edits += 1

    if reads == 0 and edits == 0:
        return []
    if reads == 0:
        return [Signal(
            name="shallow_read", target="agent", severity="warning",
            penalty=12, evidence=[], label="No reads before edits (Read:Edit = 0)",
        )]

    ratio = reads / max(edits, 1)
    if ratio >= 2.0:
        return [Signal(
            name="deep_read", target="agent", severity="info",
            penalty=0, evidence=[],
            label=f"Read:Edit = {ratio:.1f} — research-first pattern",
        )]
    return [Signal(
        name="shallow_read", target="agent", severity="warning",
        penalty=12,
        evidence=[f"Read:Edit = {ratio:.1f} (< 2.0 threshold)"],
        label=f"Read:Edit = {ratio:.1f} — low research depth",
    )]


# ── Low diversity ────────────────────────────────────────────────────────

def _detect_low_diversity(messages: list[dict], task_type: str) -> list[Signal]:
    """Detect narrow tool usage.

    Only fires on coding sessions where tool diversity matters.
    Research/brainstorm sessions naturally use 1-2 tools (web_search, web_extract).
    """
    if task_type != TASK_CODING:
        return []
    tool_names: set[str] = set()
    call_count = 0
    for msg in messages:
        tcs = msg.get("tool_calls") or []
        if isinstance(tcs, dict):
            tcs = [tcs]
        for tc in tcs:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function", tc)
            name = fn.get("name", "") if isinstance(fn, dict) else ""
            if name:
                call_count += 1
                tool_names.add(name)

    if call_count >= 5 and len(tool_names) <= 2:
        return [Signal(
            name="low_diversity", target="agent", severity="info",
            penalty=5,
            evidence=[f"{len(tool_names)} tools across {call_count} calls"],
            label=f"Only {len(tool_names)} tool types in {call_count} calls",
        )]
    return []


# ── Runtime errors (not signals — logged separately) ─────────────────────

def _collect_runtime_errors(messages: list[dict]) -> list[RuntimeLog]:
    """Collect tool outputs that contain explicit errors.

    These are NOT signals. They don't penalise the session score.
    They're displayed in a 'Runtime Log' section so the user can see
    what actually failed — module provenance + first error line.

    Fires when:
    - Output starts with "Error:" / "ERROR:" (shell/program error)
    - Output starts with "Traceback (most recent call last):" (Python crash)
    - JSON wrapper has an "error" key (structured Hermes tool error)
    """
    logs: list[RuntimeLog] = []
    for msg in messages:
        if msg.get("role") not in ("assistant", "tool"):
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue

        # Identify which module produced this
        module = "terminal"
        tcs = msg.get("tool_calls") or []
        if isinstance(tcs, dict):
            tcs = [tcs]
        for tc in tcs:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function", tc)
            name = fn.get("name", "") if isinstance(fn, dict) else ""
            if name:
                module = name
                break

        inner = content

        # Check for structured JSON error
        if isinstance(inner, str) and inner.strip().startswith("{"):
            try:
                parsed = json.loads(inner)
                if isinstance(parsed, dict) and parsed.get("error"):
                    logs.append(RuntimeLog(
                        module=module,
                        error=str(parsed["error"])[:200],
                    ))
                    continue
                inner = parsed.get("output") or parsed.get("content") or inner
            except (json.JSONDecodeError, TypeError):
                pass

        if not isinstance(inner, str):
            continue

        inner = inner.strip()

        # Check first line — only log if the ENTIRE output is an error
        first_line = inner.split("\n")[0].strip()
        if first_line.startswith(("Error:", "ERROR:", "Traceback (most recent call last):")):
            logs.append(RuntimeLog(
                module=module,
                error=first_line[:200],
            ))
            continue

    return logs


# ── Shrinking prompts ────────────────────────────────────────────────────

def _detect_shrinking_prompts(messages: list[dict]) -> list[Signal]:
    """Detect if user prompts are getting shorter (disengagement signal)."""
    user_texts = [
        m.get("content", "")
        for m in messages
        if m.get("role") == "user" and m.get("content")
    ]
    if len(user_texts) < 4:
        return []

    first_len = len(user_texts[0])
    last_len = len(user_texts[-1])
    if last_len < first_len * 0.15 and first_len > 200:
        # Only fire if the last prompt is ALSO vague (no file paths, identifiers)
        last_has_specifics = bool(
            re.findall(r"[\w./-]+\.\w{2,4}", user_texts[-1])
            or re.findall(r"\b\d{3,}\b", user_texts[-1])
        )
        if not last_has_specifics:
            return [Signal(
                name="shrinking_prompts", target="user", severity="info",
                penalty=5,
                evidence=[user_texts[0][:80], user_texts[-1][:80]],
                label="Prompts getting shorter — possible disengagement",
            )]
    return []


# ── Extraction orchestrator ──────────────────────────────────────────────

def extract_signals(messages: list[dict], task_type: str | None = None) -> SignalResult:
    """Run all deterministic signal detectors on a conversation.

    Args:
        messages: List of message dicts with role, content, tool_calls.
        task_type: Override auto-detection. If None, auto-detect.

    Returns:
        SignalResult with all detected signals and computed metrics.
    """
    # Guard: minimum session size
    skip_reason = _check_minimum_messages(messages)
    if skip_reason:
        msg_count = len(messages)
        user_count = sum(1 for m in messages if m.get("role") == "user")
        return SignalResult(
            signals=[],
            metrics={
                "total_turns": msg_count,
                "total_tokens": 0,
                "user_turns": user_count,
                "tool_call_count": 0,
                "tool_names": [],
                "reads": 0,
                "edits": 0,
                "read_edit_ratio": 0.0,
                "user_texts": [],
                "agent_texts": [],
                "task_type": task_type or detect_task_type(messages),
            },
            skipped_reason=skip_reason,
        )

    if task_type is None:
        task_type = detect_task_type(messages)

    signals: list[Signal] = []
    detectors = [
        _detect_correction_chain,
        _detect_frustration,
        _detect_goal_drift,
        _detect_vague_prompts,
        _detect_reasoning_loops,
        _detect_premature_stop,
        _detect_tool_repetition,
        _detect_low_diversity,
        _detect_shrinking_prompts,
        _detect_read_edit_ratio,
    ]

    for detector in detectors:
        signals.extend(detector(messages, task_type) if "task_type" in detector.__code__.co_varnames else detector(messages))

    # Collect runtime errors (separate from signals — zero penalty)
    runtime_logs = _collect_runtime_errors(messages)

    # Compute full metrics
    reads = 0
    edits = 0
    tool_names: list[str] = []
    call_count = 0
    total_tokens = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total_tokens += max(1, len(content) // 4)
        tcs = msg.get("tool_calls") or []
        if isinstance(tcs, dict):
            tcs = [tcs]
        for tc in tcs:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function", tc)
            name = fn.get("name", "") if isinstance(fn, dict) else ""
            if name:
                call_count += 1
                tool_names.append(name)
                if name in READ_TOOLS:
                    reads += 1
                if name in WRITE_TOOLS:
                    edits += 1

    user_texts = [m.get("content", "") for m in messages if m.get("role") == "user"]
    agent_texts = [m.get("content", "") for m in messages if m.get("role") == "assistant"]

    return SignalResult(
        signals=signals,
        runtime_logs=runtime_logs,
        metrics={
            "total_turns": len(messages),
            "total_tokens": total_tokens,
            "user_turns": len(user_texts),
            "agent_turns": len(agent_texts),
            "tool_call_count": call_count,
            "tool_names": list(set(tool_names)),
            "reads": reads,
            "edits": edits,
            "read_edit_ratio": round(reads / max(edits, 1), 2),
            "user_texts": user_texts,
            "agent_texts": agent_texts,
            "task_type": task_type,
        },
    )