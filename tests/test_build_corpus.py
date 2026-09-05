"""Tests for build_corpus refresh mode (same-dir rescore, no copy crash)."""

import json
import shutil
import subprocess
import sys
from pathlib import Path


def _seed(tmp_path: Path) -> Path:
    src = next(iter(Path("corpus").glob("*.py")))
    shutil.copy(src, tmp_path / src.name)
    return tmp_path


def test_same_dir_refresh_rescores_without_samefile_crash():
    d = _seed(Path(__import__("tempfile").mkdtemp()))
    r = subprocess.run(
        [sys.executable, "scripts/build_corpus.py", "--traces", str(d), "--out", str(d)],
        capture_output=True, text=True, check=False, cwd=".",
    )
    assert r.returncode == 0, r.stderr[-2000:]
    assert "refreshed" in r.stdout


def test_same_dir_refresh_writes_sidecars_for_all_traces():
    d = _seed(Path(__import__("tempfile").mkdtemp()))
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
    out = tmp_path / "out"
    r = subprocess.run(
        [sys.executable, "scripts/build_corpus.py", "--traces", "corpus", "--out", str(out), "--keep", "2"],
        capture_output=True, text=True, check=False, cwd=".",
    )
    assert r.returncode == 0, r.stderr[-2000:]
    assert len(sorted(out.glob("*.py"))) == 2
