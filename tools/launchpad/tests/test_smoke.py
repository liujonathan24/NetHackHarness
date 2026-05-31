"""Smoke test: the scaffold imports and `launchpad --help` exits 0."""

from __future__ import annotations

import subprocess
import sys


def test_package_imports() -> None:
    """All public modules import without error (TUI is lazy-imported)."""
    import tools.launchpad  # noqa: F401
    import tools.launchpad.cli  # noqa: F401
    import tools.launchpad.core.git  # noqa: F401
    import tools.launchpad.core.harness  # noqa: F401
    import tools.launchpad.core.launcher  # noqa: F401
    import tools.launchpad.core.live  # noqa: F401
    import tools.launchpad.core.runs  # noqa: F401
    import tools.launchpad.core.traces  # noqa: F401
    import tools.launchpad.core.trainer  # noqa: F401
    import tools.launchpad.types  # noqa: F401


def test_help_exits_zero() -> None:
    """`python -m tools.launchpad --help` exits 0 and mentions known subcommands."""
    proc = subprocess.run(
        [sys.executable, "-m", "tools.launchpad", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    out = proc.stdout + proc.stderr
    for sub in ("eval", "train", "runs", "trace", "harness"):
        assert sub in out, f"missing subcommand '{sub}' in --help output"
