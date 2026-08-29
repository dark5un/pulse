"""Test isolation: all Hermes state lives under pytest's temporary directory."""
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_hermes_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home
