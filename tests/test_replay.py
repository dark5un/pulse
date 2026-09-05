"""Tests for pulse replay runner (plan item 1 / A1). Synthetic stub traces only."""

import sys
import textwrap

from pulse.replay import replay_corpus, replay_one


def _stub(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(textwrap.dedent(body))
    return str(p)


def test_replay_one_ok(tmp_path):
    trace = _stub(tmp_path, "ok.py", """\
        import sys
        print("done")
        """)
    out = replay_one(trace, live=False, timeout=30)
    assert out["trace"] == trace
    assert out["ok"] is True
    assert out["returncode"] == 0
    assert out["timed_out"] is False


def test_replay_one_failure(tmp_path):
    trace = _stub(tmp_path, "bad.py", """\
        import sys
        sys.exit(3)
        """)
    out = replay_one(trace, live=False, timeout=30)
    assert out["ok"] is False
    assert out["returncode"] == 3
    assert out["timed_out"] is False


def test_replay_one_timeout(tmp_path):
    trace = _stub(tmp_path, "slow.py", """\
        import time
        time.sleep(30)
        """)
    out = replay_one(trace, live=False, timeout=1)
    assert out["timed_out"] is True
    assert out["ok"] is False


def test_replay_one_passes_live_flag(tmp_path):
    trace = _stub(tmp_path, "flag.py", """\
        import sys
        print("--live" if "--live" in sys.argv else "dry")
        """)
    dry = replay_one(trace, live=False, timeout=30)
    assert "dry" in dry["output"]
    live = replay_one(trace, live=True, timeout=30)
    assert "--live" in live["output"]


def test_replay_corpus_collects_all(tmp_path):
    ok = _stub(tmp_path, "a_ok.py", 'print("a")\n')
    bad = _stub(tmp_path, "b_bad.py", 'import sys; sys.exit(1)\n')
    rows = replay_corpus([ok, bad], live=False, timeout=30, jobs=2)
    assert len(rows) == 2
    by_trace = {r["trace"]: r for r in rows}
    assert by_trace[ok]["ok"] is True
    assert by_trace[bad]["ok"] is False


def test_replay_corpus_empty():
    assert replay_corpus([], live=False) == []


def test_replay_uses_system_python(tmp_path):
    trace = _stub(tmp_path, "which.py", """\
        import sys
        print(sys.executable)
        """)
    out = replay_one(trace, live=False, timeout=30)
    assert out["ok"] is True
    # Must run under the current interpreter (has deps), not bare `python`.
    assert sys.executable in out["output"]
