"""Deep-judge gate S1 (CW-1/CW-2): corpus export + selection.

All fixtures are SYNTHETIC sessions written into a throwaway SQLite DB that
mimics the Hermes sessions/messages schema — never real transcripts.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from pulse import corpus as cp
from pulse.corpus_cli import main as corpus_main
from pulse.session_store import SchemaIncompatibleError

# ── fixture DB builder ────────────────────────────────────────────────────


def make_db(path: Path, sessions: list[dict[str, Any]]) -> Path:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, model TEXT, started_at REAL, ended_at REAL)")
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, "
        "content TEXT, tool_calls TEXT, tool_name TEXT, timestamp REAL)"
    )
    for i, sess in enumerate(sessions):
        conn.execute(
            "INSERT INTO sessions (id, model, started_at, ended_at) VALUES (?,?,?,?)",
            (sess["id"], sess.get("model", "test-model"), 1000.0 + i, 2000.0 + i),
        )
        for msg in sess["messages"]:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, tool_calls, tool_name, timestamp) "
                "VALUES (?,?,?,?,?,?)",
                (sess["id"], msg["role"], msg.get("content", ""), msg.get("tool_calls"),
                 msg.get("tool_name"), 1000.0 + i),
            )
    conn.commit()
    conn.close()
    return path


def _msgs(*pairs: tuple[str, str]) -> list[dict[str, Any]]:
    return [{"role": r, "content": c} for r, c in pairs]


def session_correcting(sid: str, extra: str = "") -> dict[str, Any]:
    """3 consecutive correction-leading user turns -> correction_chain positive."""
    return {
        "id": sid,
        "messages": _msgs(
            ("user", "Please refactor src/app.py and fix the parser bug in config.yaml" + extra),
            ("assistant", "I updated the parser and patched config.yaml accordingly."),
            ("user", "no, that broke the tests in tests/test_parser.py"),
            ("assistant", "Let me look at the failing tests and revert the change."),
            ("user", "wrong, you changed the fixture loader instead"),
            ("assistant", "Fixing the fixture loader reference now."),
            ("user", "no, still failing: revert to the original approach"),
            ("assistant", "Reverted; re-running the suite now."),
        ),
    }


def session_stopping(sid: str) -> dict[str, Any]:
    """Assistant stop-offer phrasing -> premature_stop positive (chat is gradeable)."""
    return {
        "id": sid,
        "messages": _msgs(
            ("user", "Summarize the quarterly report at reports/q3.md for the board deck"),
            ("assistant", "Here is the summary for the board deck."),
            ("user", "Add the revenue table too, in reports/q3_revenue.csv"),
            ("assistant", "Added the table from q3_revenue.csv."),
            ("user", "And the risk section"),
            ("assistant", "Done. Should I continue with the appendix, or is this a good stopping point?"),
        ),
    }


def session_plain(sid: str, n: int = 6) -> dict[str, Any]:
    body = _msgs(*[("user", f"Discuss topic {sid} part {i}, covering notes for {i}.md") for i in range(n // 2)])
    msgs: list[dict[str, Any]] = []
    for r in body:
        msgs.append(r)
        msgs.append({"role": "assistant", "content": f"Noted, continuing on {r['content'][:20]}."})
    return {"id": sid, "messages": msgs}


def session_short(sid: str) -> dict[str, Any]:
    return {"id": sid, "messages": _msgs(("user", "hi"), ("assistant", "hello!"), ("user", "bye"))}


def session_secret(sid: str) -> dict[str, Any]:
    return {
        "id": sid,
        "messages": _msgs(
            ("user", "my key is sk-proj-SuperSecretKey1234567890 and email jane.doe@example.com fix login.py"),
            ("assistant", "Patched login.py; rotated the token ghp_abcdefgh12345678 too."),
            ("user", "no, keep the env loader"),
            ("assistant", "Reverted the env loader change."),
            ("user", "wrong, only the timeout constant"),
            ("assistant", "Done, timeout constant only."),
            ("user", "no, thanks"),
            ("assistant", "Bearer abcdefGHIJ0123456789 was in the header; removed."),
        ),
    }


def long_session(sid: str) -> dict[str, Any]:
    """Big enough that build_prompt's 12k budget must cut the middle."""
    msgs = _msgs(("user", "build notes for " + sid), ("assistant", "ack"))
    for i in range(120):
        msgs.append({"role": "user", "content": f"step {i}: " + "x" * 250})
        msgs.append({"role": "assistant", "content": f"done {i}: " + "y" * 250})
    return {"id": sid, "messages": msgs}


# ── export (CW-1) ─────────────────────────────────────────────────────────


def test_export_writes_hashed_snapshots_and_skips_short(tmp_path):
    db = make_db(tmp_path / "state.db", [
        session_correcting("s-corr"),
        session_short("s-short"),
        session_plain("s-plain"),
    ])
    out = tmp_path / "corpus"
    summary = cp.export_corpus(out, db_path=db)
    assert summary.seen == 3
    assert summary.skipped_short == 1
    assert summary.exported_new == 2
    assert summary.superseded == 0
    index = cp.read_index(out)
    assert len(index["entries"]) == 2
    for name, entry in index["entries"].items():
        path = out / name
        payload = json.loads(path.read_text())
        assert name == payload_sha(entry) or name.startswith(entry["sha256"][:16])
        assert entry["session_id"] == payload["session_id"]
        assert entry["model"] and entry["task_type"] and entry["exported_at"]
        assert payload["schema"] == cp.SNAPSHOT_SCHEMA
        assert payload["redact_version"] == "v1"


def payload_sha(entry: dict[str, Any]) -> str:
    return f"{entry['sha256'][:16]}.json"


def test_skip_predicate_matches_extract_signals(tmp_path):
    # 5 msgs but only 2 user turns: extract_signals skips; export must too.
    borderline = {
        "id": "s-border",
        "messages": _msgs(
            ("user", "first prompt about the project"),
            ("assistant", "reply one"),
            ("user", "second prompt continues the work"),
            ("assistant", "reply two"),
            ("assistant", "reply three with a tool"),
        ),
    }
    from pulse.signals import extract_signals

    assert extract_signals(borderline["messages"]).skipped_reason == "insufficient_data"
    db = make_db(tmp_path / "state.db", [borderline])
    summary = cp.export_corpus(tmp_path / "corpus", db_path=db)
    assert summary.seen == 1 and summary.skipped_short == 1 and summary.exported_new == 0


def test_redact_at_write_no_secrets_on_disk(tmp_path):
    db = make_db(tmp_path / "state.db", [session_secret("s-sec")])
    out = tmp_path / "corpus"
    cp.export_corpus(out, db_path=db)
    blob = "\n".join(p.read_text() for p in out.glob("*.json"))
    for needle in ("sk-proj-SuperSecretKey", "ghp_abcdefgh", "jane.doe@example.com", "Bearer abcdefGHIJ"):
        assert needle not in blob
    assert "[REDACTED]" in blob


def test_incremental_skip_and_supersede(tmp_path):
    db = make_db(tmp_path / "state.db", [session_correcting("s1"), session_plain("s2")])
    out = tmp_path / "corpus"
    first = cp.export_corpus(out, db_path=db)
    assert first.exported_new == 2
    again = cp.export_corpus(out, db_path=db)
    assert again.skipped_unchanged == 2 and again.exported_new == 0
    # revisit s1 with changed content -> re-export, old snapshot superseded
    db2 = tmp_path / "state2.db"
    make_db(db2, [session_correcting("s1", extra=" and update docs/readme.md"), session_plain("s2")])
    third = cp.export_corpus(out, db_path=db2)
    assert third.re_exported == 1 and third.superseded == 1 and third.exported_new == 0
    records, deduped = cp.load_active_snapshots(out)
    assert deduped == 0  # supersede marking already handled
    assert len(records) == 2
    ids = {r["session_id"] for r in records}
    assert ids == {"s1", "s2"}
    index = cp.read_index(out)
    assert sum(1 for e in index["entries"].values() if e.get("superseded_by")) == 1


def test_approx_truncated_stamp(tmp_path):
    db = make_db(tmp_path / "state.db", [long_session("s-long"), session_plain("s-plain")])
    out = tmp_path / "corpus"
    cp.export_corpus(out, db_path=db)
    flags = {}
    index = cp.read_index(out)
    for entry in index["entries"].values():
        flags[entry["session_id"]] = entry["approx_truncated"]
    assert flags["s-long"] is True and flags["s-plain"] is False


def test_export_missing_db_names_path(tmp_path):
    missing = tmp_path / "nope" / "state.db"
    with pytest.raises(SchemaIncompatibleError) as exc:
        cp.export_corpus(tmp_path / "corpus", db_path=missing)
    assert str(missing) in str(exc.value)


def test_advisory_labels_are_deterministic_pair_flags(tmp_path):
    db = make_db(tmp_path / "state.db", [session_correcting("s-corr"), session_stopping("s-stop")])
    out = tmp_path / "corpus"
    cp.export_corpus(out, db_path=db)
    index = cp.read_index(out)
    pairs_by_id = {}
    for name in index["entries"]:
        payload = json.loads((out / name).read_text())
        adv = payload["advisory"]
        assert adv["pulse_version"]
        assert "extract_signals" in adv["note"]
        pairs_by_id[payload["session_id"]] = adv["det_pairs"]
    assert pairs_by_id["s-corr"]["correction_chain"] == 1
    assert pairs_by_id["s-stop"]["premature_stop"] == 1


# ── selection (CW-2) ──────────────────────────────────────────────────────


def build_corpus(tmp_path, n_corr=30, n_stop=30, n_plain=100):
    sessions = []
    for i in range(n_corr):
        sessions.append(session_correcting(f"corr-{i:03d}"))
    for i in range(n_stop):
        sessions.append(session_stopping(f"stop-{i:03d}"))
    for i in range(n_plain):
        sessions.append(session_plain(f"plain-{i:03d}"))
    db = make_db(tmp_path / "state.db", sessions)
    out = tmp_path / "corpus"
    cp.export_corpus(out, db_path=db)
    return out


def test_select_meets_floors_and_freezes_hashes(tmp_path):
    out = build_corpus(tmp_path)
    manifest = cp.select_corpus(out, n_core=50, n_enriched=50, pair_floor=10, seed=7)
    assert manifest["schema"] == cp.MANIFEST_SCHEMA
    assert manifest["seed"] == 7
    assert manifest["redact_version"] == "v1"
    assert manifest["prompt_version"] == "v1"
    assert manifest["judge"]["model"] == ""  # placeholder: identity finalized at run time
    counts = manifest["counts"]
    assert counts["core"] == 50 and counts["enriched"] == 50
    assert counts["eligible"] == 160
    for pair in cp.COMPARABLE_PAIRS:
        assert counts["det_positive"][pair]["total"] >= 10
    assert len(manifest["items"]) == 100
    ids = [it["session_id"] for it in manifest["items"]]
    assert len(set(ids)) == 100  # one snapshot version per session max
    strata = {it["stratum"] for it in manifest["items"]}
    assert strata == {"core", "enriched"}
    # hashes match the files on disk
    for it in manifest["items"]:
        assert hashlib.sha256((out / it["path"]).read_bytes()).hexdigest() == it["sha256"]
        assert it["path"] == f"{it['sha256'][:16]}.json"


def test_select_is_seeded_deterministic(tmp_path):
    out = build_corpus(tmp_path)
    a = cp.select_corpus(out, seed=42)
    b = cp.select_corpus(out, seed=42)
    assert [it["path"] for it in a["items"]] == [it["path"] for it in b["items"]]
    c = cp.select_corpus(out, seed=43)
    assert [it["path"] for it in a["items"]] != [it["path"] for it in c["items"]]


def test_select_dedupes_session_id_newest_wins(tmp_path):
    # Corpus sized so the selection covers every active snapshot
    # (25+25 positives fill enriched exactly; 50 plain fill core): a
    # session with TWO hash versions on disk must appear exactly once,
    # with the NEWEST hash.
    out = build_corpus(tmp_path, n_corr=25, n_stop=25, n_plain=50)
    db2 = tmp_path / "state2.db"
    make_db(db2, [session_plain("plain-000", n=8)])
    cp.export_corpus(out, db_path=db2)
    manifest = cp.select_corpus(out, seed=11)
    paths = [it["path"] for it in manifest["items"]]
    assert len(paths) == len(set(paths)) == 100
    assert len([it for it in manifest["items"] if it["session_id"] == "plain-000"]) == 1
    index = cp.read_index(out)
    versions = {n for n, e in index["entries"].items() if e["session_id"] == "plain-000"}
    assert len(versions) == 2  # both hash versions exist on disk
    newest = max(versions, key=lambda n: index["entries"][n]["exported_at"])
    chosen = [it["path"] for it in manifest["items"] if it["session_id"] == "plain-000"]
    assert chosen == [newest]
    assert manifest["counts"]["deduped"] == 0  # supersede marking did the dedupe


def test_select_floor_shortfall_fails_loudly(tmp_path):
    # correction_chain pool large enough, but premature_stop has zero positives:
    # the per-pair floor must fail loudly with exact pool counts, writing nothing.
    sessions = [session_correcting(f"c{i}") for i in range(12)] + [
        session_plain(f"p{i:03d}") for i in range(120)
    ]
    db = make_db(tmp_path / "state.db", sessions)
    out = tmp_path / "corpus"
    cp.export_corpus(out, db_path=db)
    with pytest.raises(cp.SelectionError) as exc:
        cp.select_corpus(out, seed=1)
    assert "premature_stop" in str(exc.value)  # the empty pool is the failure
    assert not (out / "manifests").exists() or not list((out / "manifests").glob("*.json"))


def test_select_corpus_too_small_fails(tmp_path):
    db = make_db(tmp_path / "state.db", [session_plain("only")])
    out = tmp_path / "corpus"
    cp.export_corpus(out, db_path=db)
    with pytest.raises(cp.SelectionError) as exc:
        cp.select_corpus(out)
    assert "corpus too small" in str(exc.value)


def test_select_missing_snapshot_names_it(tmp_path):
    out = build_corpus(tmp_path)
    index = cp.read_index(out)
    victim = min(index["entries"])
    (out / victim).unlink()
    with pytest.raises(cp.CorpusError) as exc:
        cp.load_active_snapshots(out)
    assert victim in str(exc.value)
    assert "re-run pulse corpus export" in str(exc.value)


def test_manifest_written_to_path_with_hash(tmp_path):
    out = build_corpus(tmp_path)
    target = tmp_path / "sel.json"
    cp.select_corpus(out, seed=5, out_path=target)
    assert target.exists()
    assert json.loads(target.read_text())["seed"] == 5


# ── CLI wiring ────────────────────────────────────────────────────────────


def test_cli_export_list_select_roundtrip(tmp_path, capsys):
    db = make_db(tmp_path / "state.db", [
        session_correcting("c1"), session_stopping("s1"), session_short("tiny"),
    ] + [session_plain(f"p{i:03d}") for i in range(10)])
    out = tmp_path / "corpus"
    rc = corpus_main(["export", "--out", str(out), "--db", str(db)])
    assert rc == 0
    printed = capsys.readouterr().out
    assert "skipped_short=1" in printed
    rc = corpus_main(["list", "--corpus", str(out)])
    assert rc == 0
    listing = capsys.readouterr().out
    assert "p000" in listing and "session_id" in listing
    rc = corpus_main(["select", "--corpus", str(out), "--out", str(tmp_path / "m.json"),
                      "--n-core", "5", "--n-enriched", "2", "--pair-floor", "1", "--seed", "3"])
    assert rc == 0
    assert (tmp_path / "m.json").exists()


def test_gitignore_posture_snapshots_ignored_manifests_tracked():
    import subprocess

    repo = Path(__file__).parents[1]
    ignored = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-q", "corpus/deadbeefdeadbeef.json"],
        check=False,
    )
    assert ignored.returncode == 0, "snapshot files must be git-ignored"
    tracked = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "corpus/manifests/manifest-x.json"],
        capture_output=True, text=True, check=False,
    )
    assert tracked.returncode != 0, "selection manifests must be committable"


def test_cli_loud_fail_missing_db(tmp_path, capsys):
    rc = corpus_main(["export", "--out", str(tmp_path / "corpus"), "--db", str(tmp_path / "gone.db")])
    assert rc == 2
    assert str(tmp_path / "gone.db") in capsys.readouterr().out


def test_cli_select_shortfall_exit2(tmp_path, capsys):
    db = make_db(tmp_path / "state.db", [session_plain(f"p{i}") for i in range(4)])
    out = tmp_path / "corpus"
    corpus_main(["export", "--out", str(out), "--db", str(db)])
    capsys.readouterr()
    rc = corpus_main(["select", "--corpus", str(out), "--out", str(tmp_path / "m.json")])
    assert rc == 2
    assert "corpus too small" in capsys.readouterr().out
    assert not (tmp_path / "m.json").exists()
