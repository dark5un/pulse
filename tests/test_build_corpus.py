"""Tests for build_corpus refresh mode (same-dir rescore, no copy crash).

Hermetic: traces are seeded fixtures, never the operator's local corpus.
"""

import json
import subprocess
import sys
from pathlib import Path

from conftest import write_unroll_trace


def _seed(tmp_path: Path) -> Path:
    write_unroll_trace(tmp_path, "refresh-check")
    return tmp_path


def test_same_dir_refresh_rescores_without_samefile_crash(tmp_path):
    d = _seed(tmp_path)
    r = subprocess.run(
        [sys.executable, "scripts/build_corpus.py", "--traces", str(d), "--out", str(d)],
        capture_output=True, text=True, check=False, cwd=".",
    )
    assert r.returncode == 0, r.stderr[-2000:]
    assert "refreshed" in r.stdout


def test_same_dir_refresh_writes_sidecars_for_all_traces(tmp_path):
    d = _seed(tmp_path)
    r = subprocess.run(
        [sys.executable, "scripts/build_corpus.py", "--traces", str(d), "--out", str(d), "--keep", "10"],
        capture_output=True, text=True, check=False, cwd=".",
    )
    assert r.returncode == 0, r.stderr[-2000:]
    traces = sorted(d.glob("*.py"))
    for t in traces:
        sidecar = d / (t.stem + ".score.json")
        assert sidecar.is_file(), f"missing sidecar for {t.name}"
        rec = json.loads(sidecar.read_text())
        assert rec["score"] == max(0, min(100, round(100 - rec["penalty"])))


def test_copy_mode_still_copies_to_different_dir(tmp_path):
    src = tmp_path / "traces"
    src.mkdir()
    write_unroll_trace(src, "copy-a", n_user=3)
    write_unroll_trace(src, "copy-b", n_user=4)
    out = tmp_path / "out"
    r = subprocess.run(
        [sys.executable, "scripts/build_corpus.py", "--traces", str(src), "--out", str(out), "--keep", "2"],
        capture_output=True, text=True, check=False, cwd=".",
    )
    assert r.returncode == 0, r.stderr[-2000:]
    assert len(sorted(out.glob("*.py"))) == 2
