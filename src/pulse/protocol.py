"""Versioned JSON stdin/stdout protocol for adapters such as Pi."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from typing import Any

from pulse.signals import extract_signals

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class NormalizedMessage:
    id: str
    parent_id: str | None
    role: str
    content: str
    tool_name: str | None
    tool_call_id: str | None
    tool_calls: list[dict[str, Any]]
    tool_error: bool
    timestamp: int | float | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class AnalysisDocument:
    schema_version: int
    harness: str
    session_id: str
    branch_leaf_id: str
    session_file: str | None
    provider: str
    model: str
    messages: list[dict[str, Any]]


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_text(x.get("text", "") if isinstance(x, dict) else x) for x in value)
    return "" if value is None else str(value)


def parse_document(payload: dict[str, Any]) -> AnalysisDocument:
    if not isinstance(payload, dict):
        raise TypeError("document must be an object")
    for key in ("schema_version", "harness", "session_id", "branch_leaf_id", "messages"):
        if key not in payload:
            raise ValueError(f"missing required field: {key}")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version: {payload['schema_version']}")
    if payload["harness"] != "pi":
        raise ValueError("harness must be pi")
    if not isinstance(payload["messages"], list):
        raise TypeError("messages must be an array")
    messages: list[dict[str, Any]] = []
    for index, raw in enumerate(payload["messages"]):
        if not isinstance(raw, dict):
            raise TypeError(f"messages[{index}] must be an object")
        if not raw.get("id") or raw.get("role") not in {"user", "assistant", "tool", "other"}:
            raise ValueError(f"messages[{index}] requires id and supported role")
        item = dict(raw)
        item["content"] = _text(item.get("content", ""))
        item["tool_calls"] = item.get("tool_calls") or []
        item["tool_error"] = bool(item.get("tool_error", False))
        messages.append(item)
    return AnalysisDocument(
        schema_version=SCHEMA_VERSION,
        harness="pi",
        session_id=str(payload["session_id"]),
        branch_leaf_id=str(payload["branch_leaf_id"]),
        session_file=payload.get("session_file"),
        provider=str(payload.get("provider") or "unknown"),
        model=str(payload.get("model") or "unknown"),
        messages=messages,
    )


class AnalysisResult(dict[str, Any]):
    """JSON-compatible result with convenient attribute access."""

    @property
    def message_count(self) -> int:
        return int(self["message_count"])

    @property
    def status(self) -> str:
        return str(self["status"])


def analyze_document(document: AnalysisDocument) -> AnalysisResult:
    result = extract_signals(document.messages)
    metrics = result.metrics
    penalties: dict[str, float] = {"user": 0.0, "agent": 0.0, "other": 0.0}
    signal_payload = []
    for signal in result.signals:
        target = signal.target if signal.target in {"user", "agent"} else "other"
        penalties[target] += max(0.0, float(signal.penalty))
        signal_payload.append({"id": signal.name, "name": signal.name, "target": signal.target,
                               "severity": signal.severity, "penalty": signal.penalty,
                               "label": signal.label, "evidence": signal.evidence[:2]})
    total = sum(penalties.values())
    score = max(0, min(100, round(100 - total)))
    total_penalty = max(total, 1.0)
    attribution = {key: round(max(0.0, 100 - value / total_penalty * 100), 2) for key, value in penalties.items()}
    attribution["user"] = round(100 - penalties["user"] / total_penalty * 100, 2)
    status = "insufficient_data" if result.skipped_reason else "ok"
    return AnalysisResult({"schema_version": SCHEMA_VERSION, "status": status,
            "session_id": document.session_id, "branch_leaf_id": document.branch_leaf_id,
            "score": score, "task_type": metrics.get("task_type", "chat"),
            "signals": signal_payload, "coaching": [s.get("label", "") for s in signal_payload if s.get("label")],
            "attribution": attribution, "provider": document.provider, "model": document.model,
            "message_count": len(document.messages), "user_turn_count": sum(m.get("role") == "user" for m in document.messages),
            "metrics": {k: v for k, v in metrics.items() if k not in {"user_texts", "agent_texts"}},
            "error": None})


def serialize_result(result: dict[str, Any]) -> str:
    return json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        result = analyze_document(parse_document(payload))
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        print(f"pulse protocol error: {exc}", file=sys.stderr)
        return 2
    print(serialize_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

__all__ = ["SCHEMA_VERSION", "AnalysisDocument", "analyze_document", "parse_document", "serialize_result"]

# Keep dataclass conversion available to adapters/tests without exposing internals.
_ = asdict
