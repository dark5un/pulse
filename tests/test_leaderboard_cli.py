"""Tests for `pulse leaderboard` CLI (Phase B2).

Hermetic: seeded unroll-trace fixtures in tmp_path — never the operator's
untracked local ``corpus/`` data (CI has none, and the gym corpus drifts).
"""

import json
import subprocess
import sys

from conftest import pulse_subprocess_env, write_score_sidecar, write_unroll_trace


def _seed_corpus(tmp_path):
    traces = [write_unroll_trace(tmp_path, f"lb-{i}", n_user=i + 3) for i in range(3)]
    for t in traces:
        write_score_sidecar(t)
    return traces


def test_leaderboard_table_on_corpus(tmp_path):
    _seed_corpus(tmp_path)
    r = subprocess.run(
        [sys.executable, "-m", "pulse", "leaderboard", "--corpus", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        env=pulse_subprocess_env(),
    )
    assert r.returncode == 0, r.stderr
    assert "BEST" in r.stdout or "best" in r.stdout.lower()


def test_leaderboard_json_is_ranked(tmp_path):
    from pulse.leaderboard_cli import load_corpus_records, render_leaderboard

    _seed_corpus(tmp_path)
    recs = load_corpus_records(tmp_path)
    assert recs, "expected records from seeded corpus"
    out = json.loads(render_leaderboard(recs, as_json=True))
    assert isinstance(out, dict)
    task = next(iter(out))
    assert "best" in out[task] and "worst" in out[task]


def test_leaderboard_live_fallback_scores_py_without_sidecar(tmp_path):
    write_unroll_trace(tmp_path, "live-fallback")  # deliberately no sidecar
    from pulse.leaderboard_cli import load_corpus_records

    recs = load_corpus_records(tmp_path)
    assert len(recs) == 1 and "score" in recs[0]


def test_task_and_top_filters(tmp_path):
    from pulse.leaderboard_cli import load_corpus_records, render_leaderboard

    _seed_corpus(tmp_path)
    recs = load_corpus_records(tmp_path)
    tasks = {r.get("task_type") for r in recs}
    task = min(str(t) for t in tasks)
    out = render_leaderboard(recs, task=task, top=1)
    assert f"== {task}" in out
    for other in tasks - {task}:
        assert f"== {other}" not in out
