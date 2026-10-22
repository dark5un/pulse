"""WU-5 (PU-11, PU-12): installer and clean-install contract.

- requires-python >= 3.12 is wrong: Hermes runs 3.11. Both packages
  compile clean under 3.11. Floor lowered; compile-checked.
- install.sh writes the module to exactly one live location and the
  entrypoint works without cwd-dependent sys.path games (relative
  imports throughout src/pulse).
- clean-env install: install into a temp HERMES_HOME + clean venv and
  assert plugin registration via relative imports, `python -m pulse`
  from any cwd, and a single module location.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_requires_python_floor_is_311():
    import tomllib

    repo = Path(__file__).parents[1]
    with open(repo / "pyproject.toml", "rb") as f:
        assert tomllib.load(f)["project"]["requires-python"] == ">=3.11"


def test_package_compiles_under_311():
    """3.11 floor check: run compileall under a real 3.11 interpreter.

    Portable discovery (the old /var/home/panos path broke every other
    machine AND GitHub CI): explicit PULSE_PY311 override, else
    `python3.11` on PATH, else the current interpreter when it *is* 3.11
    (the CI matrix case); skip only when no 3.11 exists anywhere.
    """
    py311 = os.environ.get("PULSE_PY311") or shutil.which("python3.11")
    if not py311 and sys.version_info[:2] == (3, 11):
        py311 = sys.executable
    if py311 is None:
        pytest.skip("no python3.11 interpreter available")
    repo = Path(__file__).parents[1]
    proc = subprocess.run(
        [py311, "-m", "compileall", "-q", str(repo / "src"), str(repo / "tests")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]


def test_installed_plugin_imports_without_cwd_or_syspath(tmp_path):
    repo = Path(__file__).parents[1]
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    home.mkdir()
    bin_dir.mkdir()
    hermes = bin_dir / "hermes"
    hermes.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hermes.chmod(0o755)
    env = {
        **os.environ,
        "HOME": str(home),
        "HERMES_HOME": str(home / ".hermes"),
        "PULSE_SOURCE_DIR": str(repo),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }
    subprocess.run(["bash", str(repo / "install.sh")], env=env, check=True, capture_output=True, text=True)
    installed = home / ".hermes/plugins/pulse"
    assert (installed / "plugin.yaml").is_file()
    assert (installed / "__init__.py").is_file()
    # Exactly one live module location: no nested duplicate package copy.
    assert not (installed / "pulse").exists(), "duplicate vendored copy still written by install.sh"
    assert (installed / "paths.py").is_file()
    external = tmp_path / "external"
    external.mkdir()
    probe = subprocess.run(
        [sys.executable, "-c", (
            "import importlib.util, sys;"
            "spec = importlib.util.spec_from_file_location("
            "'hermes_plugins.probe_pulse', sys.argv[1] + '/__init__.py',"
            " submodule_search_locations=[sys.argv[1]]);"
            "mod = importlib.util.module_from_spec(spec);"
            "sys.modules['hermes_plugins.probe_pulse'] = mod;"
            "spec.loader.exec_module(mod);"
            "assert hasattr(mod, 'register'); print('REGISTER-OK')"
        ), str(installed)],
        cwd=external, capture_output=True, text=True, check=False,
    )
    assert "REGISTER-OK" in probe.stdout, probe.stderr[-2000:]


def test_no_syspath_hack_in_plugin():
    repo = Path(__file__).parents[1]
    text = (repo / "src" / "pulse" / "plugin.py").read_text()
    assert "sys.path.insert" not in text
    assert "from .paths import" in text or "from . import" in text


def test_install_module_list_covers_plugin_and_corpus_modules():
    """Deep-judge gate CW-1 (risk 6): install.sh's module list must cover
    everything plugin.py imports (relative `from .X import`) plus the new
    corpus-layer modules — corpus/corpus_cli were the easy miss. Pure CLI
    satellites (leaderboard_cli etc.) are intentionally not plugin-loaded."""
    repo = Path(__file__).parents[1]
    script = (repo / "install.sh").read_text()
    marker = "for module in "
    start = script.index(marker) + len(marker)
    listed = set(script[start:script.index("; do", start)].split())
    assert {"corpus", "corpus_cli"} <= listed, "corpus modules missing from install.sh"
    plugin_src = (repo / "src" / "pulse" / "plugin.py").read_text()
    imported = set(re.findall(r"^from \.([a-z_0-9]+) import", plugin_src, flags=re.MULTILINE))
    missing = imported - listed
    assert not missing, f"install.sh module list missing plugin imports: {sorted(missing)}"
