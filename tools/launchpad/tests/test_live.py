"""Tests for tools.launchpad.core.live.

Subprocesses are mocked at `asyncio.create_subprocess_exec`; no real `prime`
or `vf-eval` invocations occur. Filesystem tests use tmp_path.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.launchpad.core import live
from tools.launchpad.types import TaskEvent, TraceTurn


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _turn_line(turn: int, reward: float = 0.0, dlvl: int = 1) -> str:
    payload: dict[str, Any] = {
        "turn": turn,
        "t_wall": float(turn),
        "variant": "test",
        "raw_grid": [],
        "status": {},
        "dlvl": dlvl,
        "hp": 10,
        "max_hp": 10,
        "max_dlvl_reached": dlvl,
        "continual_life": 1,
        "rendered_user_message": "",
        "assistant_message": "",
        "tool_calls": [],
        "action_indices": [],
        "reward": reward,
        "messages": [],
    }
    return json.dumps(payload) + "\n"


async def _collect(agen, n: int, timeout: float = 2.0) -> list[Any]:
    """Pull at most `n` items from an async generator, with a timeout."""
    out: list[Any] = []

    async def _pump() -> None:
        async for item in agen:
            out.append(item)
            if len(out) >= n:
                break

    try:
        await asyncio.wait_for(_pump(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        await agen.aclose()
    return out


# ---------------------------------------------------------------------------
# watch_trace_dir / watch_file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watch_trace_dir_emits_existing_oldest_first(tmp_path: Path) -> None:
    """Happy path: existing NDJSON lines yielded oldest-file-first."""
    a = tmp_path / "older.ndjson"
    b = tmp_path / "newer.ndjson"
    a.write_text(_turn_line(0) + _turn_line(1))
    b.write_text(_turn_line(2))
    # Force mtime ordering.
    import os

    os.utime(a, (1.0, 1.0))
    os.utime(b, (2.0, 2.0))

    results = await _collect(live.watch_trace_dir(tmp_path), n=3, timeout=1.0)
    assert [t.turn for _, t in results] == [0, 1, 2]
    assert results[0][0] == a
    assert results[2][0] == b


@pytest.mark.asyncio
async def test_watch_trace_dir_missing_raises(tmp_path: Path) -> None:
    """Edge case: nonexistent dir raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        agen = live.watch_trace_dir(tmp_path / "nope")
        await agen.__anext__()


@pytest.mark.asyncio
async def test_watch_file_skips_partial_trailing_line(tmp_path: Path) -> None:
    """Edge case: partial trailing line (no newline) is not yielded."""
    p = tmp_path / "t.ndjson"
    # one complete + one in-flight (no newline).
    p.write_text(_turn_line(0) + '{"turn": 1, "t_wall')

    results = await _collect(live.watch_file(p), n=2, timeout=0.5)
    assert [t.turn for t in results] == [0]


@pytest.mark.asyncio
async def test_watch_file_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        agen = live.watch_file(tmp_path / "missing.ndjson")
        await agen.__anext__()


# ---------------------------------------------------------------------------
# helpers: parsing
# ---------------------------------------------------------------------------


def test_parse_turn_line_skips_malformed() -> None:
    """Malformed JSON warns and returns None (never raises)."""
    with pytest.warns(UserWarning):
        assert live._parse_turn_line("{not json") is None
    assert live._parse_turn_line("") is None
    assert live._parse_turn_line(_turn_line(7)).turn == 7  # type: ignore[union-attr]


def test_parse_samples_payload_handles_shapes() -> None:
    assert live._parse_samples_payload(b"") == []
    assert live._parse_samples_payload(b'[{"id":1},{"id":2}]') == [{"id": 1}, {"id": 2}]
    assert live._parse_samples_payload(b'{"samples":[{"id":"a"}]}') == [{"id": "a"}]
    # NDJSON fallback.
    assert live._parse_samples_payload(b'{"id":1}\n{"id":2}\n') == [{"id": 1}, {"id": 2}]
    # Total garbage -> [].
    assert live._parse_samples_payload(b"not json at all") == []


# ---------------------------------------------------------------------------
# poll_hosted
# ---------------------------------------------------------------------------


def _fake_proc(stdout: bytes, returncode: int = 0) -> MagicMock:
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    proc.returncode = returncode
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=returncode)
    return proc


@pytest.mark.asyncio
async def test_poll_hosted_emits_new_samples_then_status(tmp_path: Path) -> None:
    """Happy path: first poll yields two trace_turn events + one status."""
    payload = json.dumps([{"id": "s1", "reward": 1.0}, {"id": "s2", "reward": 0.0}]).encode()

    with (
        patch.object(live.shutil, "which", return_value="/usr/bin/prime"),
        patch(
            "tools.launchpad.core.live.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=_fake_proc(payload)),
        ),
    ):
        agen = live.poll_hosted("eval-abc", interval_s=10.0)
        events = await _collect(agen, n=3, timeout=1.0)

    kinds = [e.kind for e in events]
    assert kinds == ["trace_turn", "trace_turn", "status"]
    assert all(isinstance(e, TaskEvent) for e in events)
    assert events[2].payload["new_samples"] == 2
    assert events[2].payload["total_samples"] == 2


@pytest.mark.asyncio
async def test_poll_hosted_missing_prime_raises() -> None:
    """Edge case: missing `prime` on PATH -> FileNotFoundError."""
    with patch.object(live.shutil, "which", return_value=None):
        with pytest.raises(FileNotFoundError):
            agen = live.poll_hosted("eval-x")
            await agen.__anext__()


@pytest.mark.asyncio
async def test_poll_hosted_dedupes_across_polls() -> None:
    """Edge case: a sample seen on poll 1 is not re-emitted on poll 2."""
    p1 = json.dumps([{"id": "s1"}]).encode()
    p2 = json.dumps([{"id": "s1"}, {"id": "s2"}]).encode()

    procs = [_fake_proc(p1), _fake_proc(p2)]

    async def _spawn(*_args: Any, **_kwargs: Any) -> MagicMock:
        return procs.pop(0)

    with (
        patch.object(live.shutil, "which", return_value="/usr/bin/prime"),
        patch("tools.launchpad.core.live.asyncio.create_subprocess_exec", new=_spawn),
        patch("tools.launchpad.core.live.asyncio.sleep", new=AsyncMock(return_value=None)),
    ):
        agen = live.poll_hosted("eval-abc", interval_s=0.0)
        # Poll 1: trace_turn(s1) + status; Poll 2: trace_turn(s2) + status.
        events = await _collect(agen, n=4, timeout=1.0)

    kinds = [e.kind for e in events]
    assert kinds == ["trace_turn", "status", "trace_turn", "status"]
    assert events[0].payload["id"] == "s1"
    assert events[2].payload["id"] == "s2"
    assert events[3].payload["new_samples"] == 1


@pytest.mark.asyncio
async def test_poll_hosted_kills_subprocess_on_cancel() -> None:
    """Cancellation must propagate and not leak a live subprocess."""
    proc = MagicMock()
    proc.communicate = AsyncMock(side_effect=asyncio.CancelledError())
    proc.returncode = None
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=-9)

    with (
        patch.object(live.shutil, "which", return_value="/usr/bin/prime"),
        patch(
            "tools.launchpad.core.live.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=proc),
        ),
    ):
        agen = live.poll_hosted("eval-xyz", interval_s=10.0)
        task = asyncio.create_task(agen.__anext__())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await agen.aclose()

    proc.kill.assert_called_once()


# ---------------------------------------------------------------------------
# tail_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tail_task_unknown_raises() -> None:
    """Unknown task_id in both registries -> KeyError."""

    async def _empty(_task_id: str):
        if False:
            yield  # pragma: no cover
        raise KeyError("nope")

    fake_launcher = MagicMock()
    fake_launcher.stream_events = MagicMock(side_effect=KeyError("nope"))
    fake_trainer = MagicMock()
    fake_trainer.stream_events = MagicMock(side_effect=KeyError("nope"))

    import sys

    with patch.dict(
        sys.modules,
        {
            "tools.launchpad.core.launcher": fake_launcher,
            "tools.launchpad.core.trainer": fake_trainer,
        },
    ):
        with pytest.raises(KeyError):
            agen = live.tail_task("missing")
            await agen.__anext__()


@pytest.mark.asyncio
async def test_tail_task_yields_stdout_lines_then_stops() -> None:
    """Happy path: yields stdout lines, stops on `finished` event."""

    async def _events(_task_id: str):
        yield TaskEvent(task_id="t", kind="stdout", t_wall=0.0, payload={"line": "hello"})
        yield TaskEvent(task_id="t", kind="stderr", t_wall=0.0, payload={"line": "skip"})
        yield TaskEvent(task_id="t", kind="stdout", t_wall=0.0, payload={"line": "world"})
        yield TaskEvent(task_id="t", kind="finished", t_wall=0.0, payload={"exit_code": 0})

    fake_launcher = MagicMock()
    fake_launcher.stream_events = _events
    fake_trainer = MagicMock()
    fake_trainer.stream_events = MagicMock(side_effect=KeyError("nope"))

    import sys

    with patch.dict(
        sys.modules,
        {
            "tools.launchpad.core.launcher": fake_launcher,
            "tools.launchpad.core.trainer": fake_trainer,
        },
    ):
        agen = live.tail_task("t")
        lines = [line async for line in agen]

    assert lines == ["hello", "world"]
