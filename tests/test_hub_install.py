"""Reproduce the Hub install flow locally, end-to-end.

The Hub does:
  1. extract README.md + nethack.py + pyproject.toml + nethack_core/ from a tarball
  2. uv pip install <env_dir> in a clean Python 3.12 venv
  3. python -c "import nethack" + load_environment()

This test creates a temp dir mimicking the extracted tarball, runs the same
install + import, and asserts no error. Catches Hub-only failures (workspace
deps, vendoring gaps, metadata format) before pushing to the Hub.

Slow (~30s); skip with `pytest -k 'not hub_install'` if you don't want it
in your fast loop.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENV_DIR = ROOT / "environments" / "nethack"


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


@pytest.mark.slow
def test_hub_install_e2e_recreates_what_the_hub_does():
    """Run the same `uv pip install + import` the Hub test_suite runs."""

    # 1. Bundle nethack_core into the env dir (same as `prime env push` does).
    bundle = subprocess.run([sys.executable, str(ROOT / "tools" / "bundle_for_hub.py")],
                            capture_output=True, text=True)
    assert bundle.returncode == 0, f"bundle failed: {bundle.stderr}"

    # 2. Spin up a clean tarball in a tempdir.
    with tempfile.TemporaryDirectory(prefix="nethack_hub_install_") as td:
        td_path = Path(td)
        for name in ("README.md", "nethack.py", "pyproject.toml"):
            shutil.copy(ENV_DIR / name, td_path / name)
        if (ENV_DIR / "nethack_core").is_dir():
            shutil.copytree(ENV_DIR / "nethack_core", td_path / "nethack_core")
        # wiki/snapshot.json is force-included via the wheel build; copy if present.
        if (ENV_DIR / "wiki").is_dir():
            shutil.copytree(ENV_DIR / "wiki", td_path / "wiki")

        # 3. uv venv (hub uses 3.12; we use whatever uv finds).
        venv_dir = td_path / ".venv"
        r = _run(["uv", "venv", str(venv_dir), "--python", "3.12"])
        assert r.returncode == 0, f"uv venv: {r.stderr}"

        # 4. uv pip install — the failure mode the Hub gates on.
        r = _run(["uv", "pip", "install", "--python", str(venv_dir / "bin" / "python"),
                  str(td_path)])
        assert r.returncode == 0, f"install failed:\n{r.stderr[:2000]}"

        # 5. import + load_environment, mirroring Hub test_install_and_import.
        r = _run([str(venv_dir / "bin" / "python"), "-c",
                  "import nethack; nethack.load_environment(); print('ok')"])
        assert r.returncode == 0, f"import/load failed:\n{r.stderr[:2000]}"
        assert "ok" in r.stdout
