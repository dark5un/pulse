"""WU-10 (Pulse half): version consistency gate.

Single version source is pyproject.toml; pulse.__version__ and
src/pulse/plugin.yaml must match it.
"""

import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_versions_agree():
    with open(ROOT / "pyproject.toml", "rb") as f:
        expected = tomllib.load(f)["project"]["version"]
    import pulse

    assert pulse.__version__ == expected
    plugin_yaml = (ROOT / "src" / "pulse" / "plugin.yaml").read_text()
    assert f"version: {expected}" in plugin_yaml
