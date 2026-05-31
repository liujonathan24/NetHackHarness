"""Spawn `prime rl` / `prime gepa` subprocesses; parse metrics.

`prime rl` is local-only (it's the deprecated alias for `prime train`; takes a
TOML config positional). `prime gepa` is also local-only. Both stream stdout
that we tail for scalar metrics.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator

from tools.launchpad.types import TaskEvent, TrainMetric, TrainSpec


def materialize_rl_toml(spec: TrainSpec, dest: Path) -> Path:
    """Write a `prime rl`-compatible TOML config from `spec` to `dest`.

    Returns the written path.

    Raises:
        ValueError: if `spec.mode != 'rl'` or required fields are missing.
    """
    raise NotImplementedError("core.trainer.materialize_rl_toml")


async def launch_rl(spec: TrainSpec, repo_root: Path) -> str:
    """Launch `prime rl <toml>`. Returns task_id.

    Sets NETHACK_HARNESS=<spec.harness> on the child.

    Raises:
        FileNotFoundError: if `prime` not on PATH.
        ValueError: if `spec.mode != 'rl'`.
    """
    raise NotImplementedError("core.trainer.launch_rl")


async def launch_gepa(spec: TrainSpec, repo_root: Path) -> str:
    """Launch `prime gepa run ...`. Returns task_id.

    Builds argv from `spec`: env positional `nethack`, --env-args JSON,
    --model, --reflection-model, --max-calls, --num-train/-N, --run-dir.

    Raises:
        FileNotFoundError: if `prime` not on PATH.
        ValueError: if `spec.mode != 'gepa'`.
    """
    raise NotImplementedError("core.trainer.launch_gepa")


async def stream_metrics(task_id: str) -> AsyncIterator[TrainMetric]:
    """Yield TrainMetric objects parsed from the subprocess's stdout.

    Closes when the process exits.

    Raises:
        KeyError: if `task_id` is unknown.
    """
    raise NotImplementedError("core.trainer.stream_metrics")
    yield  # pragma: no cover


async def stream_events(task_id: str) -> AsyncIterator[TaskEvent]:
    """Yield raw stdout/stderr/status events (parallel to stream_metrics)."""
    raise NotImplementedError("core.trainer.stream_events")
    yield  # pragma: no cover


def stop_task(task_id: str) -> bool:
    """SIGTERM (then SIGKILL after 5s grace). Returns True if killed."""
    raise NotImplementedError("core.trainer.stop_task")
