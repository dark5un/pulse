"""Shared, defensive Hermes SQLite session loader."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from pulse.paths import state_db


def _decode_tool_calls(raw: Any) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return []
    return value if isinstance(value, list) else []


def load_session(session_id: str | None = None, db_path: Path | None = None) -> tuple[list[dict], str, str]:
    db = db_path or state_db()
    if not db.exists():
        return [], "", ""
    try:
        with sqlite3.connect(str(db)) as conn:
            conn.row_factory = sqlite3.Row
            sid = session_id
            if sid is None:
                row = conn.execute("SELECT id FROM sessions ORDER BY last_activity_at DESC LIMIT 1").fetchone()
                if row is None:
                    return [], "", ""
                sid = row["id"]
            sess = conn.execute("SELECT model FROM sessions WHERE id=?", (sid,)).fetchone()
            if sess is None:
                return [], "", ""
            rows = conn.execute(
                "SELECT role, content, tool_calls, tool_name FROM messages WHERE session_id=? ORDER BY id", (sid,)
            ).fetchall()
    except sqlite3.OperationalError:
        # A non-Hermes/empty SQLite file is not a session database.
        return [], "", ""
    messages = []
    for row in rows:
        msg = {"role": row["role"], "content": row["content"] or ""}
        calls = _decode_tool_calls(row["tool_calls"])
        if row["tool_name"]:
            calls.append({"function": {"name": row["tool_name"]}})
            msg["tool_name"] = row["tool_name"]
        if calls:
            msg["tool_calls"] = calls
        messages.append(msg)
    return messages, sid, sess["model"] or "unknown"


def load_messages(session_id: str | None = None, db_path: Path | None = None) -> list[dict]:
    return load_session(session_id, db_path)[0]
