"""Deterministic signal extraction from conversation messages.

Every function in this module is a pure function: messages in,
signal list out. No side effects, no state.
"""

import json
import re
from collections import Counter

from .constants import (
    NON_ANALYTICAL,
    READ_TOOLS,
    TASK_BRAINSTORM,
    TASK_CODING,
    TASK_WRITING,
    WRITE_TOOLS,
)
from .models import RuntimeLog, Signal, SignalResult
from .task_type import detect_task_type

# ── Keyword sets (generic English defaults — ADR 0018) ──────────────────────
# These lexicons are role+content computable (no tool_calls — corpus
# snapshots carry none; ML-B7 recompute plane) and are NOT fitted to any
# single user's corpus (ADR 0017: calibration is per-user; shipped defaults
# stay generic). Contribution-extensible: adding standard correction /
# completion / continuation phrasing is welcome; adding phrases chosen by
# grep-golfing one operator's transcripts is not.

CORRECTION_STARTS: set[str] = {
    "no", "wrong", "that's not", "i meant", "not that",
    "revert", "undo", "that's not right",
}

# Generic correction/rephrase markers matched ANYWHERE in a user turn
# (the CW-8 study's marker family; start-of-turn flagging alone matched
# only 34 user turns DB-wide in the study corpus and starved the pool).
CORRECTION_MARKERS: set[str] = {
    "i meant", "not that", "that's not", "wrong", "instead",
    "redo", "do over", "start over", "you didn't", "didn't work",
    "revert", "undo",
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

# Premature-stop construct (ADR 0018): a completion CLAIM at the end of an
# assistant turn that the user then overrides with a CONTINUATION request.
# The old PREMISE_STOP_KW exact phrases had zero literal occurrences on
# real traffic ("good stopping point" is not how models offer to stop) —
# replaced by these generic claim/continuation families. A handful of the
# old phrases survive as legacy tail-claim entries.
COMPLETION_CLAIMS: set[str] = {
    "done", "finished", "all set", "complete", "completed",
    "that's all", "hope this helps", "let me know if",
    # legacy PREMISE_STOP_KW overlap (closing-statement phrasing):
    "should i continue", "want me to keep going",
    "good stopping point", "natural checkpoint",
}

CONTINUE_REQUESTS: set[str] = {
    "continue", "go on", "keep going", "carry on", "resume", "go ahead",
    "still", "what about", "finish the", "you didn't finish",
    "not finished", "what's left", "where we left",
}

GOAL_DRIFT_KW: set[str] = {
    "scrap that", "let me start over",
}

# ── Detector window constants (ADR 0018) ────────────────────────────────────

# correction_chain adjacency lives in USER-TURN space: harnesses always
# reply between user turns, so raw-row adjacency was structurally
# unfireable. >= CORRECTION_MIN_IN_WINDOW flagged turns inside any
# CORRECTION_USER_WINDOW consecutive user turns form a chain.
CORRECTION_USER_WINDOW = 3
CORRECTION_MIN_IN_WINDOW = 2

# premature_stop: claims count only in the last CLAIM_TAIL_CHARS chars of
# an assistant turn (a real closing statement, not mid-prose); the
# continuation must land within the next CONTINUE_WINDOW_TURNS user turns.
CLAIM_TAIL_CHARS = 200
CONTINUE_WINDOW_TURNS = 2


def _phrase_res(patterns: set[str]) -> list[re.Pattern[str]]:
    """Compile each phrase with word boundaries at its letter edges, so
    'done' never matches 'abandoned' and 'still' never matches 'stilts'."""
    return [re.compile(r"\b" + re.escape(p) + r"\b") for p in sorted(patterns)]


_CORRECTION_MARKER_RES = _phrase_res(CORRECTION_MARKERS)
_COMPLETION_CLAIM_RES = _phrase_res(COMPLETION_CLAIMS)
_CONTINUE_REQUEST_RES = _phrase_res(CONTINUE_REQUESTS)


def _is_correction_turn(text: str) -> bool:
    """True when a user turn starts with a correction word or contains a
    generic correction marker (user-turn flagging, ADR 0018)."""
    stripped = text.lower().strip()
    return (
        any(stripped.startswith(w) for w in CORRECTION_STARTS)
        or any(rx.search(stripped) for rx in _CORRECTION_MARKER_RES)
    )


# ── Minimum session guard ──────────────────────────────────────────────────

def _check_minimum_messages(messages: list[dict]) -> str | None:
    """Return a skip reason if the session is too short, else None.

    Requires both five total messages and three user turns. Tool/system
    rows count toward total messages but never substitute for user turns.
    """
    total_msgs = len(messages)
    user_turns = sum(1 for message in messages if message.get("role") == "user")
    if total_msgs < 5 or user_turns < 3:
        return "insufficient_data"
    return None


# ── Correction chain ──────────────────────────────────────────────────────

def _detect_correction_chain(messages: list[dict], task_type: str) -> list[Signal]:
    """Detect repeated user corrections in quick succession (ADR 0018).

    Adjacency lives in USER-TURN space: >= CORRECTION_MIN_IN_WINDOW
    correction-flagged user turns (start-word OR generic marker) inside
    any CORRECTION_USER_WINDOW consecutive user turns form a chain.
    The old raw-row-adjacency form (3 user messages with no other row
    between) was structurally unfireable: harnesses always reply in
    between, so user runs of length >= 3 essentially never occur.

    Litmus: "no, that's wrong" ... "that's not what I meant" within 3
            user turns → fires.
            Single "no, do X instead" → does not fire.
            "no" mid-sentence (no marker) → does not fire.
            Brainstorm session → does not fire.
    """
    if task_type == TASK_BRAINSTORM:
        return []

    # User turns in order, with their content validated as text.
    user_rows = [
        idx for idx, msg in enumerate(messages)
        if msg.get("role") == "user" and isinstance(msg.get("content", ""), str)
    ]
    flagged = [
        k for k, idx in enumerate(user_rows)
        if _is_correction_turn(messages[idx]["content"])
    ]

    # Cluster flagged turns: consecutive flags within window reach
    # (turn-index gap <= CORRECTION_USER_WINDOW - 1) belong to one chain.
    signals: list[Signal] = []
    cluster: list[int] = []
    for k in flagged + [None]:  # None sentinel flushes the final cluster
        if cluster and (k is None or k - cluster[-1] > CORRECTION_USER_WINDOW - 1):
            if len(cluster) >= CORRECTION_MIN_IN_WINDOW:
                evidence = [
                    messages[user_rows[t]]["content"]
                    for t in cluster[-3:]
                ]
                signals.append(Signal(
                    name="correction_chain",
                    target="user",
                    severity="warning",
                    penalty=12,
                    evidence=evidence,
                    label=(
                        f"{len(cluster)} correction-flagged turns within "
                        f"{CORRECTION_USER_WINDOW}-user-turn windows"
                    ),
                ))
            cluster = []
        if k is not None:
            cluster.append(k)

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
    """Detect an agent claiming completion mid-task that the user then
    overrides (ADR 0018).

    Construct: a completion claim inside the LAST CLAIM_TAIL_CHARS chars
    of an assistant turn ("done", "all set", ... — a closing statement,
    not mid-prose), followed by a continuation request inside the next
    CONTINUE_WINDOW_TURNS user turns. The user pushing the agent to keep
    going after its claim is the observable premature stop.

    Role+content only (computable from corpus snapshots — ML-B7 plane).
    The old PREMISE_STOP_KW exact-phrase scan had zero occurrences on
    real traffic and needed no user follow-up at all.

    Does not fire on brainstorm or research sessions,
    where reflective language is natural.
    """
    if task_type in NON_ANALYTICAL:
        return []

    signals: list[Signal] = []

    for idx, msg in enumerate(messages):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str) or not content:
            continue
        tail = content.lower()[-CLAIM_TAIL_CHARS:]
        if not any(rx.search(tail) for rx in _COMPLETION_CLAIM_RES):
            continue
        # Find a continuation request in the next CONTINUE_WINDOW_TURNS
        # user turns after this assistant row.
        continuation_idx: int | None = None
        user_turns_seen = 0
        for j in range(idx + 1, len(messages)):
            nxt = messages[j]
            if nxt.get("role") != "user":
                continue
            user_turns_seen += 1
            if user_turns_seen > CONTINUE_WINDOW_TURNS:
                break
            nxt_content = nxt.get("content", "")
            if isinstance(nxt_content, str) and any(
                rx.search(nxt_content.lower()) for rx in _CONTINUE_REQUEST_RES
            ):
                continuation_idx = j
                break
        if continuation_idx is None:
            continue
        signals.append(Signal(
            name="premature_stop",
            target="agent",
            severity="warning",
            penalty=10,
            evidence=[
                content[-CLAIM_TAIL_CHARS:],
                str(messages[continuation_idx].get("content", ""))[:CLAIM_TAIL_CHARS],
            ],
            label=(
                f"Completion claim, then user requested continuation "
                f"within {CONTINUE_WINDOW_TURNS} user turns"
            ),
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
    last_tool_module = "unknown"
    for msg in messages:
        if msg.get("role") not in ("assistant", "tool"):
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue

        # Hermes stores tool results with tool_name even when no call is present.
        module = str(msg.get("tool_name") or last_tool_module)
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
                last_tool_module = name
                break

        inner = content

        # Explicit tool error is authoritative even without an error prefix.
        if msg.get("tool_error") is True:
            logs.append(RuntimeLog(module=module, error=inner.strip()[:200]))
            continue

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