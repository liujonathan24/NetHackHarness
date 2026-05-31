"""Run discovery and summarization.

Walks `experiments/results/**` for eval JSON artifacts and `runs/**` for train
artifacts, parses metadata + light metrics, and returns `RunSummary` objects.

All functions are read-only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from tools.launchpad.types import RunSummary


def list_runs(
    root: Path,
    kind: str | None = None,
    tag: str | None = None,
    limit: int = 20,
) -> list[RunSummary]:
    """Return up to `limit` most-recent runs under `root`.

    Args:
        root: repo root (the dir containing `experiments/`).
        kind: filter by 'eval' | 'train' | None.
        tag: substring match against `RunSummary.tags`.
        limit: max number of results, newest first by `started_at`.

    Returns:
        List of `RunSummary`, newest first.

    Raises:
        FileNotFoundError: if `root/experiments` is missing.
    """
    raise NotImplementedError("core.runs.list_runs")


def get_run(root: Path, run_id: str) -> RunSummary:
    """Return one run by id.

    Raises:
        KeyError: if `run_id` is unknown.
    """
    raise NotImplementedError("core.runs.get_run")


def compare_runs(
    root: Path,
    run_a: str,
    run_b: str,
    metric: str = "scout",
) -> dict[str, float]:
    """Return `{a: float, b: float, delta: b - a}` for `metric`.

    Raises:
        KeyError: if either run_id is unknown.
        ValueError: if `metric` not present on both runs.
    """
    raise NotImplementedError("core.runs.compare_runs")


def latest_run(root: Path, kind: str | None = None) -> RunSummary:
    """Most-recently-started run, optionally filtered by kind.

    Raises:
        LookupError: if no runs match.
    """
    raise NotImplementedError("core.runs.latest_run")


def iter_trace_files(summary: RunSummary) -> Iterable[Path]:
    """Yield NDJSON trace files belonging to one run, in stable order.

    Empty iterable if `summary.trace_dir` is None or missing on disk.
    """
    raise NotImplementedError("core.runs.iter_trace_files")
