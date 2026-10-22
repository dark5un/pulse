"""Test isolation: all Hermes state lives under pytest's temporary directory.

Hermeticity rule (deep-judge gate S2): tests must never read the operator's
untracked local ``corpus/`` data — the repo runs uv in non-package mode, so
``sys.executable -m pulse`` subprocesses also need ``src`` on PYTHONPATH.
Use the helpers below to seed small self-contained fixtures instead.
"""
import json
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_hermes_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


def pulse_subprocess_env() -> dict:
    """Env for ``sys.executable -m pulse ...`` subprocesses (non-package mode)."""
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    src = str(REPO / "src")
    env["PYTHONPATH"] = src + (os.pathsep + existing if existing else "")
    return env


def write_unroll_trace(d: Path, name: str, *, n_user: int = 3, n_agent: int = 2) -> Path:
    """Write one self-contained unroll-style ``.py`` trace into ``d``."""
    lines = [
        f'SESSION_ID = "{name}"',
        'MODEL = "m-test"',
        'COST = {"cost_usd": 0.01}',
        "TIMELINE = [",
    ]
    for i in range(n_user):
        lines.append(
            f' {{"kind": "user_message", "text": "user question {i} about python code"}},'
        )
    for i in range(n_agent):
        lines.append(
            f' {{"kind": "llm_call", "text": "assistant answer {i} with enough words here"}},'
        )
    lines.append("]")
    path = d / f"{name}.py"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_score_sidecar(trace: Path) -> dict:
    """Score ``trace`` live and write its ``.score.json`` sidecar (deterministic)."""
    from pulse.trace_score import score_trace_file

    rec = score_trace_file(trace)
    (trace.parent / (trace.stem + ".score.json")).write_text(
        json.dumps(rec, indent=2), encoding="utf-8"
    )
    return rec


# ── agreement v2 manifest-plane fixtures (CW-5a) ────────────────────────────


def make_conversation(
    *, corrections: bool = False, stop_offer: bool = False, turns: int = 3
) -> list[dict]:
    """One eligible conversation (>=5 msgs, >=3 user turns) with optional
    detector triggers for the two comparable pairs. No '?' so the
    auto-detected task type is chat (not brainstorm/research): both
    pair detectors fire there."""
    correction_texts = [
        "no, that is not what I meant about the python module",
        "wrong, revert the patch you just made",
        "no, undo that change and try the other api",
    ]
    msgs: list[dict] = []
    for i in range(turns):
        if corrections:
            content = correction_texts[i % len(correction_texts)]
        else:
            content = f"fix the python api bug in module {i} and add a regression test for it"
        msgs.append({"role": "user", "content": content})
        if stop_offer and i == turns - 1:
            msgs.append(
                {
                    "role": "assistant",
                    "content": "we reached a good stopping point here, want me to keep going",
                }
            )
        else:
            msgs.append(
                {
                    "role": "assistant",
                    "content": f"answer {i}: patched the python api module and ran the test suite",
                }
            )
    return msgs


def write_snapshot(
    corpus_dir: Path,
    *,
    session_id: str,
    messages: list[dict],
    stratum: str = "core",
    model: str = "m-test",
    approx_truncated: bool = False,
    advisory_det_pairs: dict[str, int] | None = None,
) -> dict:
    """Write one pulse-corpus-snapshot/v1 file (content-hashed name) and
    return the matching manifest item."""
    import hashlib

    from pulse.signals_deep import PROMPT_VERSION, REDACT_VERSION  # noqa: F401

    payload = {
        "schema": "pulse-corpus-snapshot/v1",
        "session_id": session_id,
        "model": model,
        "started_at": "2026-10-01T00:00:00+00:00",
        "ended_at": "2026-10-01T01:00:00+00:00",
        "task_type": "chat",
        "message_count": len(messages),
        "messages": [
            {"role": m.get("role", "?"), "content": m.get("content", "")} for m in messages
        ],
        "redact_version": REDACT_VERSION,
        "approx_truncated": approx_truncated,
        "advisory": {
            "note": "advisory only (fixtures)",
            "pulse_version": "test",
            "det_signals": [],
            "det_pairs": advisory_det_pairs
            or {"correction_chain": 0, "premature_stop": 0},
        },
    }
    content = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    name = f"{digest[:16]}.json"
    (corpus_dir / name).write_text(content, encoding="utf-8")
    return {
        "path": name,
        "sha256": digest,
        "session_id": session_id,
        "stratum": stratum,
        "task_type": "chat",
        "model": model,
        "approx_truncated": approx_truncated,
        "det_pairs": dict(payload["advisory"]["det_pairs"]),
    }


def write_manifest(
    corpus_dir: Path,
    items: list[dict],
    *,
    seed: int = 7,
    judge: dict | None = None,
    prompt_version: str | None = None,
    name: str = "manifest.json",
) -> Path:
    """Write a pulse-corpus-manifest/v1 pinning ``items`` over ``corpus_dir``."""
    from pulse.signals_deep import PROMPT_VERSION, REDACT_VERSION

    manifest = {
        "schema": "pulse-corpus-manifest/v1",
        "kind": "pulse-corpus-selection",
        "variable": "test-fixture",
        "timestamp": "2026-10-22T00:00:00+00:00",
        "pulse_version": "test",
        "seed": seed,
        "corpus_dir": str(corpus_dir),
        "redact_version": REDACT_VERSION,
        "prompt_version": prompt_version or PROMPT_VERSION,
        "counts": {},
        "params": {"n_core": 0, "n_enriched": 0, "pair_floor": 0, "floors_note": "fixture"},
        "judge": judge
        or {
            "lane": "api",
            "model": "stub",
            "base_url": "",
            "model_checkpoint": None,
            "context_window": None,
        },
        "items": items,
    }
    path = corpus_dir / name
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def verdict_text(findings: dict[str, str]) -> str:
    """Judge payload for the given signal->finding map (finding=yes with
    penalty 0 stays label-positive via the findings map, no evidence
    shape required)."""
    from pulse.signals_deep import PROMPT_VERSION

    verdicts = [
        {"signal": sig, "finding": f, "penalty": 0} for sig, f in findings.items()
    ]
    return json.dumps({"prompt_version": PROMPT_VERSION, "verdicts": verdicts})
