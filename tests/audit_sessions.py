"""Run pulse on the 20 most recent sessions and audit signals."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / "workspace" / "pulse" / "src"))
from pulse.signals import extract_signals

conn = sqlite3.connect(str(Path.home() / ".hermes" / "state.db"))
conn.row_factory = sqlite3.Row

sessions = conn.execute(
    "SELECT id, message_count, title FROM sessions ORDER BY last_activity_at DESC LIMIT 20"
).fetchall()

results = []

for s in sessions:
    sid = s["id"]
    title = (s["title"] or "")[:60]
    rows = conn.execute(
        "SELECT role, content, tool_calls, tool_name FROM messages WHERE session_id=? ORDER BY id",
        (sid,)
    ).fetchall()

    msgs = []
    for r in rows:
        msg = {"role": r["role"], "content": r["content"] or ""}
        tc = r["tool_calls"]
        if tc:
            try:
                msg["tool_calls"] = json.loads(tc)
            except json.JSONDecodeError:
                pass
        tn = r["tool_name"]
        if tn:
            tc_list = msg.get("tool_calls", [])
            if not isinstance(tc_list, list):
                tc_list = []
            tc_list.append({"function": {"name": tn}})
            msg["tool_calls"] = tc_list
        msgs.append(msg)

    result = extract_signals(msgs)
    
    if result.skipped_reason:
        results.append({
            "session": sid,
            "title": title,
            "msgs": len(msgs),
            "skip": result.skipped_reason,
            "signals": [],
            "task_type": result.metrics.get("task_type", "?"),
        })
        continue

    results.append({
        "session": sid,
        "title": title,
        "msgs": len(msgs),
        "skip": None,
        "signals": [
            {"name": s.name, "target": s.target, "penalty": s.penalty, "severity": s.severity}
            for s in result.signals
        ],
        "task_type": result.metrics.get("task_type", "?") or "chat",
    })

conn.close()

# Print summary
print(f"{'Session':40s} {'Type':12s} {'Msgs':5s} Signals")
print("-" * 90)
for r in results:
    sigs = ", ".join(f"{s['name']}(-{s['penalty']})" for s in r["signals"]) if r["signals"] else "none"
    if r["skip"]:
        sigs = f"[SKIP: {r['skip']}]"
    print(f"{r['session'][:40]:40s} {r['task_type']:12s} {r['msgs']:5d} {sigs}")

print()
# Summary stats
total = len(results)
skipped = sum(1 for r in results if r["skip"])
with_signals = sum(1 for r in results if r["signals"] and not r["skip"])
total_signals = sum(len(r["signals"]) for r in results)
print(f"Total sessions: {total}")
print(f"Skipped (<5 msgs or <3 user turns): {skipped}")
print(f"Analyzed: {total - skipped}")
print(f"With signals: {with_signals}")
print(f"Total signals fired: {total_signals}")

# Signal type breakdown
from collections import Counter

sig_counter = Counter()
for r in results:
    for s in r["signals"]:
        sig_counter[s["name"]] += 1
print("\nSignal frequency:")
for name, count in sig_counter.most_common():
    print(f"  {name}: {count}x")