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
