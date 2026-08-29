"""Detect conversation task type from message patterns.

Every detector that relies on task-type context must call this
consistently, not duplicate the heuristic.
"""

from pulse.constants import (
    RESEARCH_TOOLS,
    TASK_BRAINSTORM,
    TASK_CHAT,
    TASK_CODING,
    TASK_RESEARCH,
    TASK_WRITING,
    WRITE_TOOLS,
)


def detect_task_type(messages: list[dict]) -> str:
    """Classify a conversation as brainstorm, coding, research, writing, or chat.

    Returns one of the TASK_* constants from pulse.constants.
    """
    user_texts = [m.get("content", "") for m in messages if m.get("role") == "user"]
    tool_names: list[str] = []
    for m in messages:
        tcs = m.get("tool_calls") or []
        if isinstance(tcs, dict):
            tcs = [tcs]
        for tc in tcs:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function", tc)
            name = fn.get("name", "") if isinstance(fn, dict) else ""
            if name:
                tool_names.append(name)

    all_user = " ".join(user_texts).lower()
    tool_set = set(tool_names)

    # Brainstorm is an intentional override for question-heavy research.
    q_marks = all_user.count("?")
    q_density = q_marks / max(len(all_user), 1)
    if q_density > 0.05 and (tool_set & RESEARCH_TOOLS):
        return TASK_BRAINSTORM
    if q_marks >= 4 and len(user_texts) >= 3 and not (WRITE_TOOLS & tool_set):
        return TASK_BRAINSTORM

    # Prose/document writes are writing; code-oriented writes and edits are coding.
    writing_words = ("essay", "article", "blog", "document", "prose", "letter", "readme", "markdown")
    code_words = ("function", "class", "module", "python", "code", "test", "refactor", "bug", "api")
    if "write_file" in tool_set and not (tool_set & {"terminal", "patch"}) and any(w in all_user for w in writing_words) and not any(w in all_user for w in code_words):
        return TASK_WRITING
    if WRITE_TOOLS & tool_set or "terminal" in tool_set:
        return TASK_CODING

    # Ordinary web work is research, after brainstorm has had its chance.
    if tool_set & RESEARCH_TOOLS:
        return TASK_RESEARCH

    if q_marks >= 4 and len(user_texts) >= 3:
        return TASK_BRAINSTORM

    return TASK_CHAT