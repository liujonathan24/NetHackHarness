"""Thin wrappers around `git` for the status pill + harness diffing.

All subprocesses use repo_root as cwd and `text=True`. No raise on non-zero
unless documented.
"""

from __future__ import annotations

from pathlib import Path


def current_branch(repo_root: Path) -> str:
    """Return the current branch, or 'HEAD' if detached. Empty on non-repo."""
    raise NotImplementedError("core.git.current_branch")


def short_sha(repo_root: Path) -> str:
    """Return short HEAD sha, or '' if not a repo / no commits."""
    raise NotImplementedError("core.git.short_sha")


def is_dirty(repo_root: Path) -> bool:
    """True if `git status --porcelain` is non-empty."""
    raise NotImplementedError("core.git.is_dirty")


def diff_file(repo_root: Path, path: Path) -> str:
    """Return `git diff HEAD -- <path>` as a string."""
    raise NotImplementedError("core.git.diff_file")
