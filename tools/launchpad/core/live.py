"""Live attach: watch a trace_dir for new NDJSON files / appended lines.

Local path uses `watchfiles`; hosted path polls `prime eval samples`.

Public API is defined in CONTRACTS.md section 6. This module never imports
internals from sibling `core.*` modules — it only depends on the type schema
and on subprocess primitives.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
import warnings
from pathlib import Path
from typing import AsyncIterator

from watchfiles import Change, awatch

from tools.launchpad.types import TaskEvent, TraceTurn

logger = logging.getLogger(__name__)

# Default poll cadence for hosted eval sample fetch.
_HOSTED_POLL_INTERVAL_S = 2.0

# Suffix the local writer uses for trace files.
_NDJSON_SUFFIX = ".ndjson"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _parse_turn_line(line: str) -> TraceTurn | None:
    """Parse a single NDJSON line into a TraceTurn, warning on corruption."""
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError as exc:
        warnings.warn(f"skipping malformed trace line: {exc}", stacklevel=2)
        return None
    try:
        return TraceTurn.model_validate(obj)
    except (TypeError, ValueError) as exc:
        warnings.warn(f"skipping invalid TraceTurn payload: {exc}", stacklevel=2)
        return None


async def _read_existing(path: Path) -> tuple[list[TraceTurn], int]:
    """Read whole NDJSON file; return (turns, bytes_consumed_through_last_newline)."""
    turns: list[TraceTurn] = []
    consumed = 0
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return turns, 0
    # Only consume up to the last newline; trailing partial line stays for tail.
    last_nl = raw.rfind(b"\n")
    if last_nl < 0:
        return turns, 0
    head = raw[: last_nl + 1]
    consumed = len(head)
    for line in head.decode("utf-8", errors="replace").splitlines():
        turn = _parse_turn_line(line)
        if turn is not None:
            turns.append(turn)
    return turns, consumed


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


async def watch_trace_dir(trace_dir: Path) -> AsyncIterator[tuple[Path, TraceTurn]]:
    """Yield (file_path, turn) for every NDJSON line written under `trace_dir`.

    1. Yields every existing turn (oldest-file -> newest, in-file order) first.
    2. Then follows the directory with `watchfiles.awatch`, yielding for each
       newly-appended line.

    Cancel the awaiting task to stop. Raises FileNotFoundError if `trace_dir`
    does not exist at call time.
    """
    if not trace_dir.exists():
        raise FileNotFoundError(f"trace_dir does not exist: {trace_dir}")
    if not trace_dir.is_dir():
        raise NotADirectoryError(f"not a directory: {trace_dir}")

    # Per-file byte offsets we've consumed so far.
    offsets: dict[Path, int] = {}

    # 1) Drain existing files, oldest first.
    existing = sorted(
        (p for p in trace_dir.glob(f"*{_NDJSON_SUFFIX}") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
    )
    for p in existing:
        turns, consumed = await _read_existing(p)
        offsets[p] = consumed
        for turn in turns:
            yield p, turn

    # 2) Tail forever via watchfiles.
    async for changes in awatch(trace_dir, recursive=False):
        touched: set[Path] = set()
        for change, raw_path in changes:
            p = Path(raw_path)
            if p.suffix != _NDJSON_SUFFIX:
                continue
            if change == Change.deleted:
                offsets.pop(p, None)
                continue
            touched.add(p)

        for p in sorted(touched, key=lambda q: offsets.get(q, 0)):
            try:
                data = p.read_bytes()
            except FileNotFoundError:
                offsets.pop(p, None)
                continue
            start = offsets.get(p, 0)
            # Handle truncation / rotation.
            if start > len(data):
                start = 0
            tail = data[start:]
            last_nl = tail.rfind(b"\n")
            if last_nl < 0:
                continue
            chunk = tail[: last_nl + 1]
            offsets[p] = start + len(chunk)
            for line in chunk.decode("utf-8", errors="replace").splitlines():
                turn = _parse_turn_line(line)
                if turn is not None:
                    yield p, turn


async def watch_file(path: Path) -> AsyncIterator[TraceTurn]:
    """Tail a single NDJSON file. Emits historical turns first, then tails.

    Tolerates partial trailing lines (writer mid-flush): incomplete bytes are
    retained until a newline arrives. Raises FileNotFoundError if `path` is
    missing at call time.
    """
    if not path.exists():
        raise FileNotFoundError(f"trace file does not exist: {path}")
    if not path.is_file():
        raise IsADirectoryError(f"not a regular file: {path}")

    turns, offset = await _read_existing(path)
    for turn in turns:
        yield turn

    parent = path.parent
    async for changes in awatch(parent, recursive=False):
        relevant = any(Path(p) == path for _, p in changes)
        if not relevant:
            continue
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            # File rotated away; keep watching for it to come back.
            offset = 0
            continue
        if offset > len(data):
            offset = 0  # truncation
        tail = data[offset:]
        last_nl = tail.rfind(b"\n")
        if last_nl < 0:
            continue
        chunk = tail[: last_nl + 1]
        offset += len(chunk)
        for line in chunk.decode("utf-8", errors="replace").splitlines():
            turn = _parse_turn_line(line)
            if turn is not None:
                yield turn


async def poll_hosted(
    eval_id: str, interval_s: float = _HOSTED_POLL_INTERVAL_S
) -> AsyncIterator[TaskEvent]:
    """Poll `prime eval samples <eval_id> --output json` for finished rollouts.

    Yields one TaskEvent per *new* sample (kind='trace_turn'), plus one
    kind='status' event per poll cycle describing aggregate progress.

    Raises FileNotFoundError if `prime` is not on PATH at call time.
    """
    if shutil.which("prime") is None:
        raise FileNotFoundError("'prime' CLI not found on PATH")

    seen: set[str] = set()
    while True:
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "prime",
                "eval",
                "samples",
                eval_id,
                "--output",
                "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_b, stderr_b = await proc.communicate()
            except asyncio.CancelledError:
                # Ensure subprocess does not outlive us.
                if proc.returncode is None:
                    proc.kill()
                    try:
                        await proc.wait()
                    except asyncio.CancelledError:
                        pass
                raise

            if proc.returncode != 0:
                logger.warning(
                    "prime eval samples %s exited %s: %s",
                    eval_id,
                    proc.returncode,
                    stderr_b.decode("utf-8", errors="replace").strip(),
                )
            else:
                samples = _parse_samples_payload(stdout_b)
                new_count = 0
                for sample in samples:
                    sid = _sample_id(sample)
                    if sid in seen:
                        continue
                    seen.add(sid)
                    new_count += 1
                    yield TaskEvent(
                        task_id=eval_id,
                        kind="trace_turn",
                        t_wall=time.time(),
                        payload=sample,
                    )
                yield TaskEvent(
                    task_id=eval_id,
                    kind="status",
                    t_wall=time.time(),
                    payload={"total_samples": len(seen), "new_samples": new_count},
                )
        except asyncio.CancelledError:
            raise
        except OSError as exc:
            # PATH disappeared mid-flight, or fork failed: surface and stop.
            logger.error("subprocess error polling %s: %s", eval_id, exc)
            raise

        try:
            await asyncio.sleep(interval_s)
        except asyncio.CancelledError:
            raise


def _parse_samples_payload(stdout_b: bytes) -> list[dict]:
    """Best-effort parse of `prime eval samples --output json`.

    Accepts either a top-level JSON array, an object with a 'samples' key,
    or NDJSON (one sample per line). Returns [] on any parse failure.
    """
    text = stdout_b.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        out: list[dict] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                out.append(item)
        return out
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        samples = obj.get("samples")
        if isinstance(samples, list):
            return [x for x in samples if isinstance(x, dict)]
        return [obj]
    return []


def _sample_id(sample: dict) -> str:
    """Stable id for a hosted-eval sample (best-effort)."""
    for key in ("id", "sample_id", "rollout_id", "uuid"):
        v = sample.get(key)
        if isinstance(v, (str, int)):
            return str(v)
    # Fall back to a content hash so duplicates collapse.
    try:
        return json.dumps(sample, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return repr(sample)


async def tail_task(task_id: str) -> AsyncIterator[str]:
    """Stream raw stdout lines for a live task.

    Looks up `task_id` in both the launcher and trainer registries (imported
    lazily to avoid a hard module-load dependency cycle). Raises KeyError if
    unknown to both.
    """
    # Lazy import — we treat sibling modules as black boxes (only the public
    # `stream_events` async iterator surface, per CONTRACTS.md). Use
    # importlib so test-time sys.modules patches always take effect (a
    # `from pkg import name` would bind to the cached parent attribute).
    import importlib

    _launcher = importlib.import_module("tools.launchpad.core.launcher")
    _trainer = importlib.import_module("tools.launchpad.core.trainer")

    found = False
    for src in (_launcher, _trainer):
        try:
            agen = src.stream_events(task_id)
        except KeyError:
            continue
        except NotImplementedError:
            # Sibling not wired yet; skip.
            continue
        found = True
        async for event in agen:
            if event.kind == "stdout":
                line = event.payload.get("line")
                if isinstance(line, str):
                    yield line
            if event.kind == "finished":
                return
        return

    if not found:
        raise KeyError(f"unknown task_id: {task_id}")
