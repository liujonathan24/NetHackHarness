"""Spawn `prime eval` / `vf-eval` subprocesses and stream their output.

Builds the command line per `experiments/exp16_obs_variants.py` conventions
(see PRIME CLI discovery): positional `nethack`, `--env-args` compact JSON,
`-n / -r / --max-concurrent`, then either local artifact flags or hosted
`--hosted --eval-name <slug>` (NEVER both -- hosted rejects local flags).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

from tools.launchpad.types import LaunchSpec, TaskEvent

logger = logging.getLogger(__name__)

_SIGKILL_GRACE_S: float = 5.0
_QUEUE_SENTINEL: object = object()


@dataclass
class _TaskHandle:
    """Internal record for a running subprocess."""

    task_id: str
    label: str
    process: asyncio.subprocess.Process
    queue: asyncio.Queue[TaskEvent | object]
    pump_task: asyncio.Task[None]
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    exit_code: int | None = None


# Process-global task registry. Keyed by task_id; secondary index on label.
_TASKS: dict[str, _TaskHandle] = {}
_LABELS: dict[str, str] = {}  # label -> task_id (for duplicate-launch detection)


# ---------------------------------------------------------------------------
# Command builder
# ---------------------------------------------------------------------------


def _slugify_label(label: str) -> str:
    """Slug rule from exp16: replace '/' with '-'."""
    return label.replace("/", "-")


def build_command(spec: LaunchSpec, output_dir: Path | None = None) -> list[str]:
    """Return the argv list for `prime eval run` (or `vf-eval` if `spec.local`).

    Raises:
        ValueError: if `spec.local=False and output_dir is None and not prime_hosted`.
    """
    env_args_json = json.dumps(spec.env_args, separators=(",", ":"))

    if spec.local:
        # vf-eval shape (matches local `vf-eval` CLI surface used in repo).
        argv: list[str] = [
            "vf-eval",
            "nethack",
            "--model",
            spec.model,
            "--env-args",
            env_args_json,
            "-n",
            str(spec.num_examples),
            "-r",
            str(spec.rollouts_per_example),
            "--max-concurrent",
            str(spec.max_concurrent),
        ]
        if output_dir is not None:
            argv += ["--save-results", "--output-dir", str(output_dir)]
        argv += list(spec.extra_args)
        return argv

    # prime eval (hosted or local)
    argv = [
        "prime",
        "eval",
        "run",
        "nethack",
        "--model",
        spec.model,
        "--env-args",
        env_args_json,
        "-n",
        str(spec.num_examples),
        "-r",
        str(spec.rollouts_per_example),
        "--max-concurrent",
        str(spec.max_concurrent),
    ]

    if spec.prime_hosted:
        argv += ["--hosted", "--eval-name", _slugify_label(spec.label)]
    else:
        if output_dir is None:
            raise ValueError(
                "output_dir is required for non-hosted prime eval runs "
                "(spec.local=False, spec.prime_hosted=False)"
            )
        argv += [
            "--save-results",
            "--output-dir",
            str(output_dir),
            "--abbreviated-summary",
        ]

    argv += list(spec.extra_args)
    return argv


# ---------------------------------------------------------------------------
# Subprocess management
# ---------------------------------------------------------------------------


async def _pump_stream(
    stream: asyncio.StreamReader | None,
    kind: str,
    queue: asyncio.Queue[TaskEvent | object],
    task_id: str,
) -> None:
    """Read lines from stream and enqueue TaskEvents. Quietly returns on EOF."""
    if stream is None:
        return
    while True:
        try:
            line_bytes = await stream.readline()
        except asyncio.CancelledError:
            raise
        except (OSError, ValueError) as exc:
            logger.warning("stream read failed for task %s (%s): %s", task_id, kind, exc)
            return
        if not line_bytes:
            return
        text = line_bytes.decode("utf-8", errors="replace").rstrip("\n")
        await queue.put(
            TaskEvent(
                task_id=task_id,
                kind=kind,  # type: ignore[arg-type]
                t_wall=time.time(),
                payload={"line": text},
            )
        )


async def _supervise(handle: _TaskHandle) -> None:
    """Run stdout+stderr pumps, await exit, emit a final `finished` event."""
    proc = handle.process
    try:
        stdout_pump = asyncio.create_task(
            _pump_stream(proc.stdout, "stdout", handle.queue, handle.task_id)
        )
        stderr_pump = asyncio.create_task(
            _pump_stream(proc.stderr, "stderr", handle.queue, handle.task_id)
        )
        await asyncio.gather(stdout_pump, stderr_pump, return_exceptions=False)
        exit_code = await proc.wait()
    except asyncio.CancelledError:
        # Cancellation: ensure child is dead, then re-raise.
        await _ensure_killed(proc)
        raise
    else:
        handle.exit_code = exit_code
        await handle.queue.put(
            TaskEvent(
                task_id=handle.task_id,
                kind="finished",
                t_wall=time.time(),
                payload={"exit_code": exit_code},
            )
        )
    finally:
        await handle.queue.put(_QUEUE_SENTINEL)
        handle.finished.set()
        # Drop label binding so the label may be reused once finished.
        _LABELS.pop(handle.label, None)


async def _ensure_killed(proc: asyncio.subprocess.Process) -> None:
    """Best-effort: SIGTERM then SIGKILL after grace."""
    if proc.returncode is not None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=_SIGKILL_GRACE_S)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            return
        try:
            await proc.wait()
        except asyncio.CancelledError:
            raise


async def launch_eval(
    spec: LaunchSpec,
    repo_root: Path,
    output_dir: Path | None = None,
) -> str:
    """Start the subprocess and return a task_id (unique per launch)."""
    if spec.label in _LABELS:
        raise RuntimeError(
            f"a task with label {spec.label!r} is already running "
            f"(task_id={_LABELS[spec.label]})"
        )

    argv = build_command(spec, output_dir=output_dir)
    program = argv[0]

    if shutil.which(program) is None:
        raise FileNotFoundError(
            f"required executable {program!r} not found on PATH; "
            "install `prime` (or `vf-eval`) before launching evals"
        )

    child_env = os.environ.copy()
    child_env["NETHACK_HARNESS"] = spec.harness

    logger.info("launching eval label=%s argv=%s", spec.label, argv)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(repo_root),
        env=child_env,
    )

    task_id = f"{spec.label}_{int(time.time())}"
    queue: asyncio.Queue[TaskEvent | object] = asyncio.Queue()
    handle = _TaskHandle(
        task_id=task_id,
        label=spec.label,
        process=proc,
        queue=queue,
        pump_task=asyncio.create_task(asyncio.sleep(0)),  # placeholder
    )
    handle.pump_task = asyncio.create_task(_supervise(handle))
    _TASKS[task_id] = handle
    _LABELS[spec.label] = task_id
    return task_id


async def stream_events(task_id: str) -> AsyncIterator[TaskEvent]:
    """Yield TaskEvent objects as the subprocess produces output."""
    handle = _TASKS.get(task_id)
    if handle is None:
        raise KeyError(task_id)
    queue = handle.queue
    while True:
        item = await queue.get()
        if item is _QUEUE_SENTINEL:
            return
        assert isinstance(item, TaskEvent)
        yield item


def stop_task(task_id: str) -> bool:
    """Send SIGTERM (then SIGKILL after 5s grace). Returns True if killed."""
    handle = _TASKS.get(task_id)
    if handle is None:
        raise KeyError(task_id)
    proc = handle.process
    if proc.returncode is not None:
        return False
    try:
        proc.send_signal(signal.SIGTERM)
    except ProcessLookupError:
        return False

    async def _escalate() -> bool:
        try:
            await asyncio.wait_for(proc.wait(), timeout=_SIGKILL_GRACE_S)
            return True
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                return True
            try:
                await proc.wait()
            except asyncio.CancelledError:
                raise
            return True

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Fire-and-forget; caller can `await wait_for(task_id)` to confirm.
            loop.create_task(_escalate())
            return True
        return loop.run_until_complete(_escalate())
    except RuntimeError:
        # No event loop -- fall back to blocking wait via a fresh loop.
        return asyncio.new_event_loop().run_until_complete(_escalate())


def list_tasks() -> list[str]:
    """Return live (not-yet-finished) task_ids known to this process."""
    return [tid for tid, h in _TASKS.items() if not h.finished.is_set()]


async def wait_for(task_id: str, timeout_s: float | None = None) -> int:
    """Await subprocess exit. Returns its exit code."""
    handle = _TASKS.get(task_id)
    if handle is None:
        raise KeyError(task_id)
    if timeout_s is None:
        await handle.finished.wait()
    else:
        await asyncio.wait_for(handle.finished.wait(), timeout=timeout_s)
    assert handle.exit_code is not None
    return handle.exit_code
