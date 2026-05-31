"""Live attach: watch a trace_dir for new NDJSON files / appended lines.

Local path uses `watchfiles`; hosted path polls `prime eval samples / logs`.
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

from tools.launchpad.types import TaskEvent, TraceTurn


async def watch_trace_dir(trace_dir: Path) -> AsyncIterator[tuple[Path, TraceTurn]]:
    """Yield (file_path, turn) for every new trace line written.

    Emits all existing turns first (oldest -> newest), then tails forever.
    Cancel the awaiting task to stop.

    Raises:
        FileNotFoundError: if `trace_dir` does not exist.
    """
    raise NotImplementedError("core.live.watch_trace_dir")
    yield  # pragma: no cover


async def watch_file(path: Path) -> AsyncIterator[TraceTurn]:
    """Tail one NDJSON file. Emits historical turns first, then tails."""
    raise NotImplementedError("core.live.watch_file")
    yield  # pragma: no cover


async def poll_hosted(eval_id: str, interval_s: float = 2.0) -> AsyncIterator[TaskEvent]:
    """Poll `prime eval samples <eval_id> --output json` for finished rollouts.

    Yields a TaskEvent (`kind='trace_turn'` or `'status'`) per new sample.

    Raises:
        FileNotFoundError: if `prime` not on PATH.
    """
    raise NotImplementedError("core.live.poll_hosted")
    yield  # pragma: no cover


async def tail_task(task_id: str) -> AsyncIterator[str]:
    """Stream raw stdout lines for a live task (from launcher OR trainer).

    Raises:
        KeyError: if `task_id` is unknown to both launcher and trainer.
    """
    raise NotImplementedError("core.live.tail_task")
    yield  # pragma: no cover
