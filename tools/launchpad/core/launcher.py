"""Spawn `prime eval` / `vf-eval` subprocesses and stream their output.

Builds the command line per `experiments/exp16_obs_variants.py` conventions
(see PRIME CLI discovery): positional `nethack`, `--env-args` compact JSON,
`-n / -r / --max-concurrent`, then either local artifact flags or hosted
`--hosted --eval-name <slug>` (NEVER both — hosted rejects local flags).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator

from tools.launchpad.types import LaunchSpec, TaskEvent


def build_command(spec: LaunchSpec, output_dir: Path | None = None) -> list[str]:
    """Return the argv list for `prime eval run` (or `vf-eval` if `spec.local`).

    For hosted prime runs (`spec.local=False, spec.prime_hosted=True`):
        prime eval run nethack --model <m> --env-args <json> -n N -r R
            --max-concurrent C --hosted --eval-name <slug>
    For local prime runs:
        ... --save-results --output-dir <output_dir> --abbreviated-summary
    For `spec.local=True`:
        vf-eval nethack ...   (signature TBD by implementer)

    Raises:
        ValueError: if `spec.local=False and output_dir is None and not prime_hosted`.
    """
    raise NotImplementedError("core.launcher.build_command")


async def launch_eval(
    spec: LaunchSpec,
    repo_root: Path,
    output_dir: Path | None = None,
) -> str:
    """Start the subprocess and return a task_id (unique per launch).

    The process is tracked internally; events flow through `stream_events`.
    The NETHACK_HARNESS env var is set to `spec.harness` for the child.

    Raises:
        FileNotFoundError: if `prime` (or `vf-eval`) is not on PATH.
        RuntimeError: if a process with the same `spec.label` is already live.
    """
    raise NotImplementedError("core.launcher.launch_eval")


async def stream_events(task_id: str) -> AsyncIterator[TaskEvent]:
    """Yield TaskEvent objects as the subprocess produces stdout/stderr/status.

    Closes the async iterator when the subprocess exits.

    Raises:
        KeyError: if `task_id` is unknown.
    """
    raise NotImplementedError("core.launcher.stream_events")
    yield  # pragma: no cover  -- makes this a valid async generator stub


def stop_task(task_id: str) -> bool:
    """Send SIGTERM (then SIGKILL after 5s grace). Returns True if killed."""
    raise NotImplementedError("core.launcher.stop_task")


def list_tasks() -> list[str]:
    """Return live task_ids known to this process."""
    raise NotImplementedError("core.launcher.list_tasks")


async def wait_for(task_id: str, timeout_s: float | None = None) -> int:
    """Await subprocess exit. Returns its exit code.

    Raises:
        KeyError: if `task_id` is unknown.
        asyncio.TimeoutError: if `timeout_s` elapses.
    """
    raise NotImplementedError("core.launcher.wait_for")
