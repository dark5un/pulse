"""Cost attribution, join-side (plan item 6 / C2-b): the honest LLM bill.

No capture change: the grouping key (team/feature) lives in a session
registry CSV the team already has (``session_id,team``). Sessions with no
mapping land in ``unmapped`` — never silently dropped. Capture-side tags
(``HERMES_SESSION_TAGS`` at trace time) are a separate unroll change.
"""

from __future__ import annotations

import csv


def load_mapping(csv_path: str) -> dict[str, str]:
    """Load session_id -> group label from a ``session_id,team`` CSV."""
    mapping: dict[str, str] = {}
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            sid = (row.get("session_id") or "").strip()
            team = (row.get("team") or "").strip()
            if sid and team:
                mapping[sid] = team
    return mapping


def rollup(records: list[dict], mapping: dict[str, str]) -> dict[str, dict]:
    """Group cost by team: totals, session counts, per-task split."""
    out: dict[str, dict] = {}
    for rec in records:
        group = mapping.get(str(rec.get("session_id", "")), "unmapped")
        card = out.setdefault(
            group, {"sessions": 0, "total_usd": 0.0, "by_task": {}}
        )
        card["sessions"] += 1
        card["total_usd"] = round(card["total_usd"] + float(rec.get("cost_usd", 0.0)), 4)
        task = str(rec.get("task_type", "coding"))
        card["by_task"][task] = round(
            card["by_task"].get(task, 0.0) + float(rec.get("cost_usd", 0.0)), 4
        )
    return out


__all__ = ["load_mapping", "rollup"]
