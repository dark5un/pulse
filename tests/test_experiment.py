"""Tests for experiment manifest + bundle/verify (plan item 4 / B3+B4)."""

import hashlib
import json
from pathlib import Path


def _trace(tmp_path, name="t.py"):
    p = tmp_path / name
    p.write_text('SESSION_ID = "s1"\nMODEL = "m"\nTIMELINE = []\n')
    return p


def test_manifest_pins_versions_and_hashes(tmp_path):
    from pulse.experiment import write_manifest

    trace = _trace(tmp_path)
    m = write_manifest(str(tmp_path / "exp"), [str(trace)], variable="model=m2")
    assert m["variable"] == "model=m2"
    assert "timestamp" in m and "pulse_version" in m
    assert m["traces"][0]["sha256"] == hashlib.sha256(trace.read_bytes()).hexdigest()
    assert (tmp_path / "exp" / "manifest.json").exists()


def test_manifest_empty_traces(tmp_path):
    from pulse.experiment import write_manifest

    m = write_manifest(str(tmp_path / "exp"), [], variable="prompt=v2")
    assert m["traces"] == []


def test_bundle_copies_trace_sidecar_manifest(tmp_path):
    from pulse.artifact import bundle

    trace = _trace(tmp_path / "src" if False else tmp_path)
    sidecar = tmp_path / "t.score.json"
    sidecar.write_text(json.dumps({"score": 90}))
    dest = bundle(str(trace), out_dir=str(tmp_path / "art"))
    assert (tmp_path / "art" / "t.artifact" / "t.py").exists()
    assert (tmp_path / "art" / "t.artifact" / "t.score.json").exists()
    assert (tmp_path / "art" / "t.artifact" / "run-manifest.json").exists()
    assert dest.endswith("t.artifact")


def test_bundle_missing_sidecar_still_bundles(tmp_path):
    from pulse.artifact import bundle

    trace = _trace(tmp_path)
    dest = bundle(str(trace), out_dir=str(tmp_path / "art"))
    assert "no sidecar" in Path(f"{dest}/run-manifest.json").read_text()


def test_verify_clean_trace(tmp_path):
    from pulse.artifact import bundle, verify

    trace = _trace(tmp_path)
    (tmp_path / "t.score.json").write_text(json.dumps({"score": 100, "penalty": 0}))
    dest = bundle(str(trace), out_dir=str(tmp_path / "art"))
    out = verify(dest)
    assert out["replays"] is True
    assert out["score_reproduces"] is True
    assert "score" in out["detail"]
