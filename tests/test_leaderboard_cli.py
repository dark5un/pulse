"""Tests for `pulse leaderboard` CLI (Phase B2)."""

import json
import subprocess
import sys


def test_leaderboard_table_on_corpus():
    r = subprocess.run(
        [sys.executable, "-m", "pulse", "leaderboard", "--corpus", "corpus"],
        capture_output=True,
        text=True,
        check=False,
        cwd=".",
    )
    assert r.returncode == 0, r.stderr
    assert "BEST" in r.stdout or "best" in r.stdout.lower()


def test_leaderboard_json_is_ranked():
    from pulse.leaderboard_cli import load_corpus_records, render_leaderboard

    recs = load_corpus_records("corpus")
    assert recs, "expected records from local corpus"
    out = json.loads(render_leaderboard(recs, as_json=True))
    assert isinstance(out, dict)
    task = next(iter(out))
    assert "best" in out[task] and "worst" in out[task]


def test_leaderboard_live_fallback_scores_py_without_sidecar(tmp_path):
    import shutil

    src = next(iter(__import__("pathlib").Path("corpus").glob("*.py")))
    shutil.copy(src, tmp_path / src.name)  # no sidecar copied
    from pulse.leaderboard_cli import load_corpus_records

    recs = load_corpus_records(str(tmp_path))
    assert len(recs) == 1 and "score" in recs[0]
