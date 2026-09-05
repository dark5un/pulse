"""Tests for `pulse portability` CLI (Phase E2)."""

import json
import subprocess
import sys
from pathlib import Path


def _write_sidecar(d: Path, name: str, model: str, skills: list, deadweight: list):
    rec = {
        "session_id": name,
        "model": model,
        "score": 90,
        "penalty": 10,
        "cost_usd": 0.01,
        "task_type": "coding",
        "active_skills": skills,
        "signals": [
            {
                "name": "skill_deadweight",
                "severity": "warning",
                "penalty": 8,
                "label": f"Skill '{s}' loaded but unused",
                "evidence": [f"skill '{s}' loaded but unused before corrections"],
            }
            for s in deadweight
        ],
    }
    (d / f"{name}.score.json").write_text(json.dumps(rec))


def test_portability_table_and_json(tmp_path):
    _write_sidecar(tmp_path, "s1", "m1", ["skill-a"], [])
    _write_sidecar(tmp_path, "s2", "m2", ["skill-a", "skill-b"], [])
    _write_sidecar(tmp_path, "s3", "m1", ["skill-b"], ["skill-b"])
    r = subprocess.run(
        [sys.executable, "-m", "pulse", "portability", "--corpus", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert "portable" in r.stdout and "model_specific" in r.stdout
    r2 = subprocess.run(
        [sys.executable, "-m", "pulse", "portability", "--corpus", str(tmp_path), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    out = json.loads(r2.stdout)
    assert out["skill-a"]["verdict"] == "portable"
    assert out["skill-b"]["verdict"] == "model_specific"


def test_sidecar_writer_includes_active_skills():
    from pulse.trace_score import score_trace_file

    corpus = sorted(Path("corpus").glob("*.py"))
    assert corpus
    rec = score_trace_file(corpus[0])
    assert "active_skills" in rec and isinstance(rec["active_skills"], list)


def test_portability_live_fallback_no_sidecar(tmp_path):
    import shutil

    src = next(iter(Path("corpus").glob("*.py")))
    shutil.copy(src, tmp_path / src.name)
    r = subprocess.run(
        [sys.executable, "-m", "pulse", "portability", "--corpus", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
