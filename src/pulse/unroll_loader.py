"""Load unroll trace files without executing them.

Trace files are generated Python scripts (replayable agent runs). They must
never be imported or exec'd — only the top-level constant assignments we care
about are extracted via ``ast.literal_eval``.
"""

import ast
from dataclasses import dataclass, field

WANTED_KEYS = ("SESSION_ID", "MODEL", "PROVIDER", "TIMELINE", "USAGE",
               "COST", "STATE_GRAPH", "DEPENDENCIES", "ACTIVE_SKILLS",
               "TOOL_SCHEMAS", "PROVIDER_CONFIG", "RESPONSE_CACHE")


@dataclass
class UnrollBundle:
    session_id: str = ""
    model: str = ""
    provider: str = ""
    timeline: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0
    state_graph: dict = field(default_factory=dict)
    dependencies: dict = field(default_factory=dict)
    active_skills: list = field(default_factory=list)
    tool_schemas: list = field(default_factory=list)


def load_unroll_trace(path: str) -> UnrollBundle:
    with open(path) as f:
        text = f.read()
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as e:
        raise ValueError(f"cannot parse trace file: {e}") from e
    found: dict = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in WANTED_KEYS:
                    try:
                        found[t.id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                        continue
    cost = found.get("COST", {}) or {}
    return UnrollBundle(
        session_id=found.get("SESSION_ID", ""),
        model=found.get("MODEL", ""),
        provider=found.get("PROVIDER", ""),
        timeline=found.get("TIMELINE", []) or [],
        usage=found.get("USAGE", {}) or {},
        cost_usd=float(cost.get("cost_usd", 0.0) or 0.0),
        state_graph=found.get("STATE_GRAPH", {}) or {},
        dependencies=found.get("DEPENDENCIES", {}) or {},
        active_skills=found.get("ACTIVE_SKILLS", []) or [],
        tool_schemas=found.get("TOOL_SCHEMAS", []) or [],
    )


def bundle_to_messages(bundle: UnrollBundle) -> list[dict]:
    """Map TIMELINE kinds to Pulse message roles (best-effort)."""
    msgs: list[dict] = []
    for entry in bundle.timeline:
        kind = entry.get("kind", "")
        if kind == "user_message":
            msgs.append({"role": "user", "content": entry.get("text", "")})
        elif kind == "llm_call":
            msgs.append({"role": "assistant", "content": entry.get("text", "")})
        elif kind == "tool_call":
            msgs.append({"role": "tool", "content": entry.get("name", "")})
        elif kind == "system_prompt":
            msgs.append({"role": "system", "content": entry.get("text", "")})
    return msgs
