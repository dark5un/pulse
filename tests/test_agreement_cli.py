"""Tests for `pulse agreement` v2 (CW-5a data plane + CW-5b reporting via
the CLI). Manifest-pinned snapshots + hermetic stub judges — never network,
never the operator's local corpus."""

import json

import pytest
from conftest import (
    make_conversation,
    verdict_text,
    write_manifest,
    write_snapshot,
)

from pulse.signals_deep import PROMPT_VERSION

EMPTY_VERDICTS = json.dumps({"prompt_version": PROMPT_VERSION, "verdicts": []})
ALL_NO = verdict_text(
    {
        "correction_quality": "no",
        "goal_completion": "no",
        "hallucination": "no",
        "context_retention": "no",
    }
)


def _stubbed_cli(monkeypatch, texts):
    """Patch make_backend with a counting StubJudge scripted with `texts`."""
    import pulse.agreement_cli as cli
    from pulse.judge import JudgeResult, StubJudge

    monkeypatch.setenv("PULSE_JUDGE_CONTEXT", "16384")  # batch budget knob (ADR 0010)

    calls = {"n": 0}

    class CountingJudge(StubJudge):
        def judge(self, prompt):
            calls["n"] += 1
            return super().judge(prompt)

    script = [JudgeResult(text=t) for t in texts]

    def _make(args):
        return CountingJudge(script)

    monkeypatch.setattr(cli, "make_backend", _make)
    return cli, calls


def _corpus(tmp_path, specs):
    """specs: list of (session_id, kwargs-for-make_conversation, stratum)."""
    d = tmp_path / "corpus"
    d.mkdir()
    items = []
    for sid, conv_kw, stratum in specs:
        items.append(
            write_snapshot(
                d, session_id=sid, messages=make_conversation(**conv_kw), stratum=stratum
            )
        )
    return d, write_manifest(d, items)


# ── cache + resume contract (M0) ──────────────────────────────────────────


def test_cache_hit_avoids_backend_call(monkeypatch, tmp_path, capsys):
    _d, man = _corpus(tmp_path, [("s1", {}, "core")])
    cli, calls = _stubbed_cli(monkeypatch, [EMPTY_VERDICTS])
    cache = tmp_path / "cache.json"
    # all-abstain cells refuse -> gate NOT EVALUATED (exit 2, never bare FAIL)
    assert cli.main(["--manifest", str(man), "--cache", str(cache)]) == 2
    assert calls["n"] == 1
    capsys.readouterr()
    assert cli.main(["--manifest", str(man), "--cache", str(cache)]) == 2
    assert calls["n"] == 1
    assert "cache hits" in capsys.readouterr().out.lower()


def test_judge_call_failure_exits_2_names_snapshot_keeps_cache(monkeypatch, tmp_path, capsys):
    """M0: dead endpoint at record #2 -> exit 2, snapshot named, #1 flushed."""
    import pulse.agreement_cli as cli
    from pulse.judge import JudgeBackend, JudgeResult

    _d, man = _corpus(tmp_path, [("s1", {}, "core"), ("s2", {}, "core")])
    cache = tmp_path / "cache.json"

    class FlakyJudge(JudgeBackend):
        model = "flaky"
        base_url = ""

        def __init__(self):
            super().__init__()
            self.n = 0

        def judge(self, prompt):
            self.n += 1
            if self.n == 1:
                return JudgeResult(text=EMPTY_VERDICTS)
            raise ConnectionError("endpoint died mid-batch")

    monkeypatch.setenv("PULSE_JUDGE_CONTEXT", "16384")
    flaky = FlakyJudge()
    monkeypatch.setattr(cli, "make_backend", lambda args: flaky)

    rc = cli.main(["--manifest", str(man), "--cache", str(cache)])
    assert rc == 2, "loud failure must exit 2 naming the failed snapshot"
    err = capsys.readouterr().err
    assert "judge call failure on snapshot" in err
    victim = json.loads(man.read_text())["items"][1]["path"]
    assert victim in err
    assert len(json.loads(cache.read_text())) == 1, "per-record flush: #1 intact"

    # Rerun: #1 served from cache, #2 judged fresh.
    cli, calls = _stubbed_cli(monkeypatch, [EMPTY_VERDICTS])
    rc2 = cli.main(["--manifest", str(man), "--cache", str(cache)])
    assert calls["n"] == 1, "rerun resumes from cache, not zero"
    assert rc2 == 2  # gate not evaluated (tiny n) — never a bare FAIL
    assert len(json.loads(cache.read_text())) == 2


def test_failure_drill_script_green():
    """scripts/drill_judge_failure.py proves the contract against a CLOSED port."""
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    r = subprocess.run(
        [sys.executable, "scripts/drill_judge_failure.py"],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo,
        timeout=180,
    )
    assert r.returncode == 0, r.stdout + "\n" + r.stderr
    assert "DRILL PASS" in r.stdout


# ── finding-aware cache + abstain round-trip ───────────────────────────────

ABSTAIN_VERDICTS = verdict_text(
    {
        "correction_quality": "unscoreable",
        "goal_completion": "no",
        "hallucination": "no",
        "context_retention": "no",
    }
)


def test_cache_value_is_finding_aware_and_abstain_survives_reload(monkeypatch, tmp_path, capsys):
    """G3: v2 cache VALUE = {signal: finding}; an abstain round-trips
    through disk reload and stays excluded from its kappa cell."""
    _d, man = _corpus(tmp_path, [("s1", {}, "core")])
    cli, _ = _stubbed_cli(monkeypatch, [ABSTAIN_VERDICTS])
    cache = tmp_path / "cache.json"
    assert cli.main(["--manifest", str(man), "--cache", str(cache)]) == 2
    value = next(iter(json.loads(cache.read_text()).values()))
    assert value == {
        "correction_quality": "unscoreable",
        "goal_completion": "no",
        "hallucination": "no",
        "context_retention": "no",
    }
    capsys.readouterr()

    class NeverJudge:
        model = "never"
        base_url = ""

        def judge(self, prompt):
            raise AssertionError("cache hit must not reach the backend")

    monkeypatch.setattr(cli, "make_backend", lambda args: NeverJudge())
    rc = cli.main(["--manifest", str(man), "--cache", str(cache), "--json"])
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["run"]["cache_hits"] == 1
    cells = {(c["pair"], c["stratum"]): c for c in out["cells"]}
    corr = cells[("correction_chain", "core")]
    assert corr["abstained"] == 1 and corr["comparable_n"] == 0  # unscoreable excluded
    stop = cells[("premature_stop", "core")]
    assert stop["abstained"] == 0 and stop["marginals"]["judge"]["neg"] == 1
    assert stop["refusal"] and "degenerate" in stop["refusal"]  # all-negative -> refused
    assert stop["kappa"] is None  # the pe=1 sentinel NEVER surfaces (ML-B6)


def test_absent_verdict_counts_as_abstain_not_no(monkeypatch, tmp_path, capsys):
    """Omission laundering fix: verdicts [] -> abstain on BOTH pairs."""
    _d, man = _corpus(tmp_path, [("s1", {}, "core")])
    cli, _ = _stubbed_cli(monkeypatch, [EMPTY_VERDICTS])
    rc = cli.main(
        ["--manifest", str(man), "--cache", str(tmp_path / "cache.json"), "--json"]
    )
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    for pair in ("correction_chain", "premature_stop"):
        cell = next(c for c in out["cells"] if c["pair"] == pair and c["stratum"] == "core")
        assert cell["abstained"] == 1 and cell["comparable_n"] == 0
    assert out["run"]["cache_hits"] == 0  # empty findings still cached


# ── grounding + prompt measurement printing ───────────────────────────────


def test_grounding_rate_prints_on_fresh_calls(monkeypatch, tmp_path, capsys):
    text = json.dumps(
        {
            "prompt_version": PROMPT_VERSION,
            "verdicts": [
                {
                    "signal": "hallucination",
                    "finding": "yes",
                    "penalty": 10,
                    "evidence": ["fix the python api bug in module 0"],
                },
                {
                    "signal": "goal_completion",
                    "finding": "yes",
                    "penalty": 10,
                    "evidence": ["a totally fabricated quote not in the transcript"],
                },
            ],
        }
    )
    _d, man = _corpus(tmp_path, [("s1", {}, "core")])
    cli, _ = _stubbed_cli(monkeypatch, [text])
    cli.main(["--manifest", str(man), "--cache", str(tmp_path / "cache.json")])
    out = capsys.readouterr().out
    assert "evidence grounding: 1/2 quotes grounded (50.0%)" in out
    assert "prompt size (fresh calls):" in out and "max=" in out
    assert "hallucination judge-rate=1.0 (1/1)" in out


# ── frozen membership + loud corpus failures (CW-5a) ──────────────────────


def test_missing_snapshot_loud_fail(monkeypatch, tmp_path, capsys):
    d, man = _corpus(tmp_path, [("s1", {}, "core"), ("s2", {}, "core")])
    for it in json.loads(man.read_text())["items"]:
        (d / it["path"]).unlink()  # snapshots gone, manifest kept
    cli, calls = _stubbed_cli(monkeypatch, [EMPTY_VERDICTS])
    rc = cli.main(["--manifest", str(man), "--cache", str(tmp_path / "c.json")])
    assert rc == 2
    err = capsys.readouterr().err
    assert "2 of 2 missing; re-run pulse corpus export" in err
    assert calls["n"] == 0, "no GPU time may be spent on an unpinned corpus"


def test_snapshot_hash_must_match_manifest(monkeypatch, tmp_path, capsys):
    d, man = _corpus(tmp_path, [("s1", {}, "core")])
    item = json.loads(man.read_text())["items"][0]
    (d / item["path"]).write_text(
        (d / item["path"]).read_text().replace("m-test", "m-mutated"), encoding="utf-8"
    )
    cli, calls = _stubbed_cli(monkeypatch, [EMPTY_VERDICTS])
    rc = cli.main(["--manifest", str(man), "--cache", str(tmp_path / "c.json")])
    assert rc == 2
    assert "content hash != manifest" in capsys.readouterr().err
    assert calls["n"] == 0


def test_manifest_prompt_version_pinned(monkeypatch, tmp_path, capsys):
    d = tmp_path / "corpus"
    d.mkdir()
    item = write_snapshot(d, session_id="s1", messages=make_conversation())
    man = write_manifest(d, [item], prompt_version="v1")
    cli, calls = _stubbed_cli(monkeypatch, [EMPTY_VERDICTS])
    rc = cli.main(["--manifest", str(man), "--cache", str(tmp_path / "c.json")])
    assert rc == 2
    assert "prompt_version" in capsys.readouterr().err
    assert calls["n"] == 0


def test_limit_below_manifest_labeled_not_evaluated(monkeypatch, tmp_path, capsys):
    _d, man = _corpus(tmp_path, [(f"s{i}", {}, "core") for i in range(3)])
    cli, _ = _stubbed_cli(monkeypatch, [ALL_NO] * 3)
    rc = cli.main(["--manifest", str(man), "--limit", "2", "--cache", str(tmp_path / "c.json")])
    assert rc == 2
    out = capsys.readouterr().out
    assert "below-manifest sample, gate not evaluated" in out
    assert "gate: NOT EVALUATED" in out
    assert "FAIL" not in out  # never a bare gate FAIL on a sample


# ── ML-B7: detector labels recomputed at run time ─────────────────────────


def test_advisory_sidecar_never_feeds_kappa(monkeypatch, tmp_path, capsys):
    """Manifest/sidecar says correction_chain=1; the messages do NOT fire
    the detector — run-time recomputation wins."""
    d = tmp_path / "corpus"
    d.mkdir()
    item = write_snapshot(
        d,
        session_id="s1",
        messages=make_conversation(),  # no corrections, no stop offer
        advisory_det_pairs={"correction_chain": 1, "premature_stop": 1},
    )
    man = write_manifest(d, [item])
    cli, _ = _stubbed_cli(monkeypatch, [ALL_NO])
    rc = cli.main(["--manifest", str(man), "--cache", str(tmp_path / "c.json"), "--json"])
    assert rc == 2
    cells = json.loads(capsys.readouterr().out)["cells"]
    for c in cells:
        if c["stratum"] == "core":
            assert c["marginals"]["detector"]["pos"] == 0  # recomputed, not advisory


def test_run_time_ineligible_snapshot_excluded(monkeypatch, tmp_path, capsys):
    """Detector thresholds can drift: an item that extract_signals skips at
    RUN time is excluded loudly, judge untouched (GPU saved)."""
    d, man = _corpus(tmp_path, [("s1", {}, "core")])
    item = json.loads(man.read_text())["items"][0]
    payload = json.loads((d / item["path"]).read_text())
    payload["messages"] = payload["messages"][:2]  # too short -> skipped
    content = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    import hashlib

    digest = hashlib.sha256(content.encode()).hexdigest()
    (d / f"{digest[:16]}.json").write_text(content, encoding="utf-8")
    item["path"] = f"{digest[:16]}.json"
    item["sha256"] = digest
    man.write_text(
        json.dumps(
            {**json.loads(man.read_text()), "items": [item]},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    cli, calls = _stubbed_cli(monkeypatch, [EMPTY_VERDICTS])
    rc = cli.main(["--manifest", str(man), "--cache", str(tmp_path / "c.json"), "--json"])
    assert rc == 2
    assert calls["n"] == 0, "run-time-ineligible items must not cost a judge call"
    err = capsys.readouterr().err
    assert "run-time ineligible" in err and "insufficient_data" in err


# ── full gate semantics through the CLI (exit 0 / exit 1) ────────────────


def _gate_corpus(tmp_path, n_per_stratum=52, pos_frac=0.5, flip=0):
    """Balanced non-degenerate corpus: half the items fire BOTH detectors,
    half fire neither. `flip` items get judge verdicts that disagree."""
    d = tmp_path / "corpus"
    d.mkdir()
    items, texts = [], []
    idx = 0
    for stratum in ("core", "enriched"):
        for i in range(n_per_stratum):
            positive = i < int(n_per_stratum * pos_frac)
            kw = {"corrections": positive, "stop_offer": positive}
            items.append(
                write_snapshot(
                    d, session_id=f"s{idx}", messages=make_conversation(**kw), stratum=stratum
                )
            )
            agree = "yes" if positive else "no"
            disagree = "no" if positive else "yes"
            finding_corr = disagree if idx < flip else agree
            finding_stop = disagree if flip <= idx < 2 * flip else agree
            texts.append(
                verdict_text(
                    {
                        "correction_quality": finding_corr,
                        "goal_completion": finding_stop,
                        "hallucination": "no",
                        "context_retention": "no",
                    }
                )
            )
            idx += 1
    return d, write_manifest(d, items), texts


def test_gate_pass_exits_0(monkeypatch, tmp_path, capsys):
    """All 4 cells kappa 1.0 at n=52 per stratum -> PASS, exit 0."""
    _d, man, texts = _gate_corpus(tmp_path)
    cli, calls = _stubbed_cli(monkeypatch, texts)
    rc = cli.main(["--manifest", str(man), "--cache", str(tmp_path / "c.json")])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert calls["n"] == 104
    assert "gate: PASS min_cell_kappa=1.0" in out
    assert "counts toward gate (min over cells)" in out
    assert "pooled" in out and "descriptive only" in out


def test_gate_fail_exits_1_with_low_cell(monkeypatch, tmp_path, capsys):
    """Flipped judge verdicts pull the core cells under the bar -> FAIL, exit 1."""
    _d, man, texts = _gate_corpus(tmp_path, flip=12)
    cli, _ = _stubbed_cli(monkeypatch, texts)
    rc = cli.main(["--manifest", str(man), "--cache", str(tmp_path / "c.json")])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "gate: FAIL" in out and "correction_chain×core" in out
    assert "kappa=0.538" in out  # core cells land below the 0.6 bar


def test_degenerate_zero_positive_corpus_refuses_every_cell(monkeypatch, tmp_path, capsys):
    """G2-shaped data (zero detector positives) must print honest refusal
    cells with distribution blocks — NOT kappa=0.0, NOT a bare FAIL."""
    _d, man, texts = _gate_corpus(tmp_path, n_per_stratum=4, pos_frac=0.0)
    cli, _ = _stubbed_cli(monkeypatch, texts)
    rc = cli.main(["--manifest", str(man), "--cache", str(tmp_path / "c.json")])
    out = capsys.readouterr().out
    assert rc == 2
    assert out.count("REFUSED — gate not evaluated: degenerate labels") == 4
    assert "kappa=0.000" not in out  # no kappa LINE (pe=1 sentinel stays buried in the reason text)
    assert "gate: NOT EVALUATED" in out
    for line in (
        "items=4 abstained=0 (0.0%) comparable-n=4",
        "marginals: judge pos=0 neg=4 | detector pos=0 neg=4",
        "confusion: tp=0 fp=0 fn=0 tn=4",
        "pe=1 base-rate collapse",
    ):
        assert line in out, line


# ── stratum + enriched cell printing ─────────────────────────────────────


def test_both_strata_cells_print(monkeypatch, tmp_path, capsys):
    _d, man, texts = _gate_corpus(tmp_path, n_per_stratum=3, pos_frac=1 / 3)
    cli, _ = _stubbed_cli(monkeypatch, texts)
    cli.main(["--manifest", str(man), "--cache", str(tmp_path / "c.json")])
    out = capsys.readouterr().out
    for header in (
        "correction_chain × core",
        "correction_chain × enriched",
        "premature_stop × core",
        "premature_stop × enriched",
    ):
        assert header in out, header
    # tiny n -> descriptive kappa but gate not evaluated per cell
    assert out.count("DESCRIPTIVE ONLY") == 4
    assert "gate: NOT EVALUATED" in out


if __name__ == "__main__":  # convenience
    raise SystemExit(pytest.main([__file__, "-q"]))
