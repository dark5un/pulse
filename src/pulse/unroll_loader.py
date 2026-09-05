"""Load unroll trace files without executing them.

Trace files are generated Python scripts (replayable agent runs). They must
never be imported or exec'd — only the top-level constant assignments we care
about are extracted via ``ast.literal_eval``.
"""

import ast
import os
from dataclasses import dataclass, field

WANTED_KEYS = ("SESSION_ID", "MODEL", "PROVIDER", "TIMELINE", "USAGE",
               "COST", "STATE_GRAPH", "DEPENDENCIES", "ACTIVE_SKILLS",
               "TOOL_SCHEMAS", "PROVIDER_CONFIG", "RESPONSE_CACHE", "SESSION_TAGS")

#: Reject trace files larger than this before reading (DoS guard).
MAX_TRACE_BYTES = 8 * 1024 * 1024
#: Reject literals with more AST nodes than this before literal_eval.
MAX_AST_NODES = 200_000
#: Reject literals nested deeper than this (RecursionError guard).
MAX_LITERAL_DEPTH = 100

#: Max number of timeline entries accepted.
MAX_TIMELINE_ENTRIES = 100_000


class TraceSchemaError(ValueError):
    """A trace constant has the wrong type or shape. Names the field."""


def _check_node_budget(node: ast.AST) -> None:
    count = 0
    max_depth = 0
    stack: list[tuple[ast.AST, int]] = [(node, 1)]
    while stack:
        current, depth = stack.pop()
        count += 1
        if count > MAX_AST_NODES:
            raise TraceSchemaError(
                f"trace literal exceeds {MAX_AST_NODES} AST nodes — refusing to evaluate"
            )
        if depth > max_depth:
            max_depth = depth
            if max_depth > MAX_LITERAL_DEPTH:
                raise TraceSchemaError(
                    f"trace literal nested deeper than {MAX_LITERAL_DEPTH} — refusing to evaluate"
                )
        stack.extend((child, depth + 1) for child in ast.iter_child_nodes(current))


def _require_mapping(value: object, field: str) -> dict:
    if not isinstance(value, dict):
        raise TraceSchemaError(f"{field} must be a mapping, got {type(value).__name__}")
    return value


def _require_list(value: object, field: str) -> list:
    if not isinstance(value, list):
        raise TraceSchemaError(f"{field} must be a list, got {type(value).__name__}")
    return value


def _require_str_list(value: object, field: str) -> list:
    items = _require_list(value, field)
    for i, item in enumerate(items):
        if not isinstance(item, str):
            raise TraceSchemaError(f"{field}[{i}] must be a string, got {type(item).__name__}")
    return items


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
    session_tags: list = field(default_factory=list)


def load_unroll_trace(path: str) -> UnrollBundle:
    try:
        size = os.path.getsize(path)
    except OSError as e:
        raise TraceSchemaError(f"cannot stat trace file: {e}") from e
    if size > MAX_TRACE_BYTES:
        raise TraceSchemaError(
            f"trace file too large ({size} bytes > {MAX_TRACE_BYTES}) — refusing to load"
        )
    with open(path) as f:
        text = f.read()
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as e:
        raise TraceSchemaError(f"cannot parse trace file: {e}") from e
    found: dict = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in WANTED_KEYS:
                    try:
                        _check_node_budget(node.value)
                        found[t.id] = ast.literal_eval(node.value)
                    except TraceSchemaError:
                        raise
                    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                        continue
    cost_raw = found.get("COST", None)
    if cost_raw is None:
        cost_raw = {}
    cost = _require_mapping(cost_raw, "COST")
    cost_usd_raw = cost.get("cost_usd", 0.0) or 0.0
    if isinstance(cost_usd_raw, bool) or not isinstance(cost_usd_raw, (int, float)):
        raise TraceSchemaError(f"COST.cost_usd must be numeric, got {type(cost_usd_raw).__name__}")
    timeline_raw = found.get("TIMELINE", None)
    if timeline_raw is None:
        timeline_raw = []
    timeline = _require_list(timeline_raw, "TIMELINE")
    if len(timeline) > MAX_TIMELINE_ENTRIES:
        raise TraceSchemaError(f"TIMELINE has {len(timeline)} entries (max {MAX_TIMELINE_ENTRIES})")
    for i, entry in enumerate(timeline):
        if not isinstance(entry, dict):
            raise TraceSchemaError(f"TIMELINE[{i}] must be a mapping, got {type(entry).__name__}")
    usage = _require_mapping(found.get("USAGE", None) if found.get("USAGE", None) is not None else {}, "USAGE")
    session_id = found.get("SESSION_ID", "")
    if not isinstance(session_id, str):
        raise TraceSchemaError(f"SESSION_ID must be a string, got {type(session_id).__name__}")
    model = found.get("MODEL", "")
    if not isinstance(model, str):
        raise TraceSchemaError(f"MODEL must be a string, got {type(model).__name__}")
    provider = found.get("PROVIDER", "")
    if not isinstance(provider, str):
        raise TraceSchemaError(f"PROVIDER must be a string, got {type(provider).__name__}")
    state_graph_raw = found.get("STATE_GRAPH", None)
    dependencies_raw = found.get("DEPENDENCIES", None)
    active_skills_raw = found.get("ACTIVE_SKILLS", None)
    tool_schemas_raw = found.get("TOOL_SCHEMAS", None)
    session_tags_raw = found.get("SESSION_TAGS", None)
    return UnrollBundle(
        session_id=session_id,
        model=model,
        provider=provider,
        timeline=timeline,
        usage=usage,
        cost_usd=float(cost_usd_raw),
        state_graph=_require_mapping(state_graph_raw if state_graph_raw is not None else {}, "STATE_GRAPH"),
        dependencies=_require_mapping(dependencies_raw if dependencies_raw is not None else {}, "DEPENDENCIES"),
        active_skills=_require_str_list(active_skills_raw if active_skills_raw is not None else [], "ACTIVE_SKILLS"),
        tool_schemas=_require_list(tool_schemas_raw if tool_schemas_raw is not None else [], "TOOL_SCHEMAS"),
        session_tags=_require_str_list(list(session_tags_raw if session_tags_raw is not None else []), "SESSION_TAGS"),
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
