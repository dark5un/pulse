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

    # Coding: reads + writes, terminal, file ops (most specific — check FIRST)
    if WRITE_TOOLS & tool_set:
        return TASK_CODING

    # Research: heavy web_search / web_extract, no edits
    if tool_set & RESEARCH_TOOLS and not (tool_set & WRITE_TOOLS):
        return TASK_RESEARCH

    # Writing: only write_file, no exec
    if "write_file" in tool_set and "terminal" not in tool_set:
        return TASK_WRITING

    # Brainstorm: high question density, few writes, research tools
    # Only classify as brainstorm after coding/research/writing ruled out
    q_marks = all_user.count("?")
    q_density = q_marks / max(len(all_user), 1)
    if q_density > 0.05 and (tool_set & RESEARCH_TOOLS):
        return TASK_BRAINSTORM
    if q_marks >= 4 and len(user_texts) >= 3:
        return TASK_BRAINSTORM

    return TASK_CHAT