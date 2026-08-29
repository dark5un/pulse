import os
import subprocess
from pathlib import Path


def test_manifest_and_offline_install_uninstall(tmp_path: Path) -> None:
    repo = Path(__file__).parents[1]
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    home.mkdir(); bin_dir.mkdir()
    hermes = bin_dir / "hermes"
    hermes.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hermes.chmod(0o755)
    env = {**os.environ, "HOME": str(home), "HERMES_HOME": str(home / ".hermes"), "PULSE_SOURCE_DIR": str(repo), "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    subprocess.run(["bash", str(repo / "install.sh")], env=env, check=True, capture_output=True, text=True)
    installed = home / ".hermes/plugins/pulse"
    assert (installed / "plugin.yaml").is_file()
    assert (installed / "__init__.py").is_file()
    assert not (installed / "__init__.py").is_symlink()
    external = tmp_path / "external"
    external.mkdir()
    probe = subprocess.run(["python", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import pulse", str(installed)],
                           cwd=external, env={"PATH": env["PATH"], "HOME": str(home), "HERMES_HOME": str(home / ".hermes")},
                           check=False, capture_output=True, text=True)
    assert probe.returncode == 0, probe.stderr
    subprocess.run(["bash", str(repo / "uninstall.sh")], env=env, check=True, capture_output=True, text=True)
    assert not installed.exists()
