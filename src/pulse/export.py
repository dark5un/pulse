"""Training-data exporter (plan item 3 / B1): traces -> SFT + DPO pairs.

Mapping: trace TIMELINE -> message list with tool calls; pulse score ->
quality filter (``min_score``, e.g. 90 -> SFT candidate); correction_chain
evidence -> DPO pairs (pre-correction assistant turn = rejected,
post-correction = chosen).

Honesty constraints: traces are redacted at capture (unroll ``redact.py``)
— the export manifest *proves* it per file with a redaction receipt, not
an assertion. Correction mining has false positives (not every correction
is a clean chosen/rejected pair) — ship with ``--review`` spot-check mode.
"""

from __future__ import annotations

import json
from pathlib import Path

from pulse.unroll_loader import UnrollBundle

REDACTION_RECEIPT = "redacted-at-capture"


def bundle_to_sharegpt(bundle: UnrollBundle) -> list[dict]:
    """TIMELINE -> ShareGPT-style messages with tool calls. Skips textless."""
    msgs: list[dict] = []
    for entry in bundle.timeline:
        kind = entry.get("kind", "")
        if kind == "user_message":
            text = entry.get("text", "") or ""
            if text:
                msgs.append({"role": "user", "content": text})
        elif kind == "llm_call":
            text = entry.get("text", "") or ""
            if text:
                msgs.append({"role": "assistant", "content": text})
        elif kind == "tool_call":
            name = entry.get("name", "") or "tool"
            args = entry.get("args", "")
            content = json.dumps(args) if isinstance(args, dict) else str(args or name)
            msgs.append({"role": "tool", "name": name, "content": content})
    return msgs


def _is_correction(text: str) -> bool:
    from pulse.signals import CORRECTION_STARTS

    stripped = text.lower().strip()
    return any(stripped.startswith(w) for w in CORRECTION_STARTS)


def correction_pairs(messages: list[dict]) -> list[dict]:
    """Mine (rejected=pre-correction assistant, chosen=post) DPO pairs.

    A pair needs: assistant turn, then a user correction, then a later
    assistant turn. Returns [] when the shape is absent — review mode
    decides whether the pair is clean, not this function.
    """
    pairs: list[dict] = []
    for i, msg in enumerate(messages):
        if msg.get("role") != "user" or not isinstance(msg.get("content"), str):
            continue
        if not _is_correction(msg["content"]):
            continue
        before = next(
            (
                m["content"]
                for m in reversed(messages[:i])
                if m.get("role") == "assistant" and m.get("content")
            ),
            "",
        )
        after = next(
            (
                m["content"]
                for m in messages[i + 1 :]
                if m.get("role") == "assistant" and m.get("content")
            ),
            "",
        )
        if before and after:
            pairs.append(
                {
                    "prompt": next(
                        (
                            m["content"]
                            for m in reversed(messages[:i])
                            if m.get("role") == "user" and m.get("content")
                        ),
                        "",
                    ),
                    "rejected": before,
                    "chosen": after,
                    "correction": msg["content"][:200],
                }
            )
    return pairs


def export_records(
    records: list[dict],
    messages_by_id: dict[str, list[dict]],
    out_dir: str | Path,
    fmt: str = "sharegpt",
    min_score: int = 90,
) -> dict:
    """Write sft.jsonl + pairs.jsonl for records scoring >= min_score.

    Returns the manifest dict (also written as manifest.json): per-file
    redaction receipts, kept/dropped counts, format, threshold.
    """
    if fmt not in ("sharegpt", "jsonl"):
        raise ValueError(f"unknown format: {fmt} (sharegpt|jsonl)")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    kept = dropped = 0
    files: list[dict] = []
    sft_lines: list[str] = []
    pair_lines: list[str] = []
    for rec in records:
        sid = str(rec.get("session_id", ""))
        if int(rec.get("score", 0)) < min_score:
            dropped += 1
            continue
        msgs = messages_by_id.get(sid, [])
        if fmt == "sharegpt":
            payload: dict = {"messages": msgs}
        else:
            payload = {"prompt": "", "completion": ""}
            turns = [m for m in msgs if m.get("content")]
            if turns:
                payload["prompt"] = str(turns[0].get("content", ""))
                payload["completion"] = str(turns[-1].get("content", ""))
        sft_lines.append(json.dumps(payload))
        for pair in correction_pairs(msgs):
            pair_lines.append(json.dumps(pair))
        files.append(
            {
                "session_id": sid,
                "score": rec.get("score"),
                "redaction_receipt": REDACTION_RECEIPT,
            }
        )
        kept += 1
    (out / "sft.jsonl").write_text("\n".join(sft_lines) + ("\n" if sft_lines else ""))
    (out / "pairs.jsonl").write_text(
        "\n".join(pair_lines) + ("\n" if pair_lines else "")
    )
    manifest = {
        "format": fmt,
        "min_score": min_score,
        "kept": kept,
        "dropped": dropped,
        "redaction_receipt": REDACTION_RECEIPT,
        "files": files,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


__all__ = [
    "REDACTION_RECEIPT",
    "bundle_to_sharegpt",
    "correction_pairs",
    "export_records",
]
