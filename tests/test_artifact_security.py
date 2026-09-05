"""WU-1 (PU-1): artifact verification must never execute trace code.

``pulse verify`` inspects a downloaded artifact. Trace files are generated
Python scripts, so executing one during verification is arbitrary host code
execution. These tests pin the non-executing contract:

- ``verify()`` returns ``{"loads", "hash_matches", "score_reproduces",
  "detail"}`` — the old ``replays`` key (\"the script exited 0\") is gone.
- A trace whose top level runs hostile code verifies without running it.
- Tampered bytes fail the hash check; missing/unparseable traces fail loads.
"""

import hashlib
import json
from pathlib import Path


def _clean_trace_text() -> str:
    return (
        'SESSION_ID = "s1"\n'
        'MODEL = "m"\n'
        'PROVIDER = "p"\n'
        'TIMELINE = [{"kind": "user_message", "text": "hi"}]\n'
        'USAGE = {}\n'
        'COST = {"cost_usd": 0.0}\n'
        'ACTIVE_SKILLS = []\n'
    )


def _bundle_text(tmp_path: Path, trace_text: str, name: str = "t.py") -> Path:
    from pulse.artifact import bundle

    src_dir = tmp_path / "src"
    src_dir.mkdir(exist_ok=True)
    trace = src_dir / name
    trace.write_text(trace_text)
    return Path(bundle(str(trace), out_dir=str(tmp_path / "art")))


def test_verify_result_schema_has_no_replays_key(tmp_path: Path) -> None:
    from pulse.artifact import verify

    dest = _bundle_text(tmp_path, _clean_trace_text())
    out = verify(dest)
    assert set(out) == {"loads", "hash_matches", "score_reproduces", "detail"}
    assert "replays" not in out


def test_verify_does_not_execute_malicious_trace(tmp_path: Path) -> None:
    from pulse.artifact import verify

    marker = tmp_path / "pwned"
    malicious = f'from pathlib import Path\nPath(r"{marker}").write_text("pwned")\n' + _clean_trace_text()
    dest = _bundle_text(tmp_path, malicious)
    out = verify(dest)
    assert not marker.exists()
    assert out["loads"] is True
    assert out["hash_matches"] is True


def test_verify_legitimate_artifact_reproduces(tmp_path: Path) -> None:
    from pulse.artifact import verify
    from pulse.trace_score import score_trace_file

    src_dir = tmp_path / "src"
    src_dir.mkdir(exist_ok=True)
    trace = src_dir / "t.py"
    trace.write_text(_clean_trace_text())
    rec = score_trace_file(trace)
    (src_dir / "t.score.json").write_text(json.dumps({"score": rec["score"], "penalty": rec["penalty"]}))

    from pulse.artifact import bundle

    dest = Path(bundle(str(trace), out_dir=str(tmp_path / "art")))
    out = verify(dest)
    assert out == {
        "loads": True,
        "hash_matches": True,
        "score_reproduces": True,
        "detail": out["detail"],
    }


def test_verify_detects_tampered_trace(tmp_path: Path) -> None:
    from pulse.artifact import verify

    dest = _bundle_text(tmp_path, _clean_trace_text())
    trace_file = dest / "t.py"
    trace_file.write_text(trace_file.read_text() + "\n# tampered after bundling\n")
    out = verify(dest)
    assert out["loads"] is True
    assert out["hash_matches"] is False
    assert "MISMATCH" in out["detail"]


def test_verify_detects_hash_mismatch_against_manifest(tmp_path: Path) -> None:
    from pulse.artifact import verify

    dest = _bundle_text(tmp_path, _clean_trace_text())
    manifest = dest / "run-manifest.json"
    data = json.loads(manifest.read_text())
    data["sha256"] = "0" * 64
    manifest.write_text(json.dumps(data))
    out = verify(dest)
    assert out["hash_matches"] is False


def test_verify_empty_dir_reports_no_trace(tmp_path: Path) -> None:
    from pulse.artifact import verify

    out = verify(tmp_path)
    assert out["loads"] is False
    assert out["hash_matches"] is False
    assert out["score_reproduces"] is False
    assert "no trace found" in out["detail"]


def test_verify_rejects_trace_missing_required_constants(tmp_path: Path) -> None:
    from pulse.artifact import bundle, verify

    src_dir = tmp_path / "src"
    src_dir.mkdir(exist_ok=True)
    trace = src_dir / "t.py"
    trace.write_text('X = 1\n')
    dest = Path(bundle(str(trace), out_dir=str(tmp_path / "art")))
    out = verify(dest)
    assert out["loads"] is False
    assert "TIMELINE" in out["detail"]


def test_verify_rejects_unparseable_trace(tmp_path: Path) -> None:
    from pulse.artifact import bundle, verify

    src_dir = tmp_path / "src"
    src_dir.mkdir(exist_ok=True)
    trace = src_dir / "t.py"
    trace.write_text("def broken(:\n")
    dest = Path(bundle(str(trace), out_dir=str(tmp_path / "art")))
    out = verify(dest)
    assert out["loads"] is False


def test_bundle_manifest_carries_schema_version(tmp_path: Path) -> None:
    from pulse import artifact as artifact_mod

    dest = _bundle_text(tmp_path, _clean_trace_text())
    manifest = json.loads((dest / "run-manifest.json").read_text())
    assert manifest["artifact_schema"] == artifact_mod.ARTIFACT_SCHEMA
    assert manifest["sha256"] == hashlib.sha256((dest / "t.py").read_bytes()).hexdigest()


def test_pulse_version_falls_back_to_package_version(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from importlib.metadata import PackageNotFoundError

    import pulse
    from pulse import artifact as artifact_mod

    def _raise(_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr(artifact_mod, "version", _raise)
    assert artifact_mod._pulse_version() == pulse.__version__
    assert artifact_mod._pulse_version() != "dev"


def test_bundle_manifest_never_records_dev(tmp_path: Path) -> None:
    dest = _bundle_text(tmp_path, _clean_trace_text())
    manifest = json.loads((dest / "run-manifest.json").read_text())
    assert manifest["pulse_version"] != "dev"


def test_package_version_matches_pyproject() -> None:
    import tomllib

    import pulse

    repo = Path(__file__).parents[1]
    with open(repo / "pyproject.toml", "rb") as f:
        declared = tomllib.load(f)["project"]["version"]
    assert pulse.__version__ == declared
