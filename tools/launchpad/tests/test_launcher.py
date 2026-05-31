"""Tests for `core.launcher` — no real subprocesses are spawned."""

from __future__ import annotations

import asyncio
import json
import signal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.launchpad.core import launcher
from tools.launchpad.types import LaunchSpec, TaskEvent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    """Clear launcher's process-global registry between tests."""
    launcher._TASKS.clear()
    launcher._LABELS.clear()
    yield
    launcher._TASKS.clear()
    launcher._LABELS.clear()


def _make_spec(**overrides: Any) -> LaunchSpec:
    base: dict[str, Any] = dict(
        label="exp_demo",
        model="anthropic/claude-3-5-sonnet",
        harness="default",
        env_args={"explicit_seeds": [1, 2]},
        num_examples=4,
        rollouts_per_example=2,
        max_concurrent=2,
        local=False,
        prime_hosted=True,
    )
    base.update(overrides)
    return LaunchSpec(**base)


def _mock_process(
    stdout_lines: list[bytes] | None = None,
    stderr_lines: list[bytes] | None = None,
    exit_code: int = 0,
) -> MagicMock:
    """Build a fake asyncio.subprocess.Process."""
    stdout_lines = list(stdout_lines or [])
    stderr_lines = list(stderr_lines or [])

    stdout = MagicMock()
    stderr = MagicMock()

    async def _read_factory(buf: list[bytes]):
        async def _readline() -> bytes:
            if buf:
                return buf.pop(0)
            return b""

        return _readline

    stdout.readline = AsyncMock(side_effect=_factory_seq(stdout_lines))
    stderr.readline = AsyncMock(side_effect=_factory_seq(stderr_lines))

    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = stderr
    proc.returncode = None

    async def _wait() -> int:
        proc.returncode = exit_code
        return exit_code

    proc.wait = AsyncMock(side_effect=_wait)
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.send_signal = MagicMock()
    return proc


def _factory_seq(lines: list[bytes]):
    """Side-effect callable: pop one line per call, then yield EOF (b'')."""
    buf = list(lines)

    async def _call(*_a, **_kw) -> bytes:
        if buf:
            return buf.pop(0)
        return b""

    return _call


# ---------------------------------------------------------------------------
# build_command
# ---------------------------------------------------------------------------


def test_build_command_hosted_default() -> None:
    spec = _make_spec(label="frontier/E2")
    argv = launcher.build_command(spec)
    assert argv[:4] == ["prime", "eval", "run", "nethack"]
    assert "--hosted" in argv
    # Slug rule: slashes -> dashes.
    eval_name_idx = argv.index("--eval-name")
    assert argv[eval_name_idx + 1] == "frontier-E2"
    # No local-only flags allowed under --hosted.
    assert "--save-results" not in argv
    assert "--output-dir" not in argv
    assert "--abbreviated-summary" not in argv
    # env_args is compact JSON.
    ea_idx = argv.index("--env-args")
    assert argv[ea_idx + 1] == json.dumps(
        {"explicit_seeds": [1, 2]}, separators=(",", ":")
    )


def test_build_command_local_prime_requires_output_dir(tmp_path: Path) -> None:
    spec = _make_spec(prime_hosted=False)
    with pytest.raises(ValueError):
        launcher.build_command(spec, output_dir=None)
    argv = launcher.build_command(spec, output_dir=tmp_path)
    assert "--save-results" in argv
    assert "--output-dir" in argv
    assert str(tmp_path) in argv
    assert "--abbreviated-summary" in argv
    assert "--hosted" not in argv


def test_build_command_vf_eval_local() -> None:
    spec = _make_spec(local=True)
    argv = launcher.build_command(spec)
    assert argv[0] == "vf-eval"
    assert "nethack" in argv


# ---------------------------------------------------------------------------
# launch_eval + stream_events (happy path)
# ---------------------------------------------------------------------------


def test_launch_and_stream_happy_path(tmp_path: Path) -> None:
    spec = _make_spec()
    proc = _mock_process(
        stdout_lines=[b"hello\n", b"world\n"],
        stderr_lines=[b"warn-1\n"],
        exit_code=0,
    )

    async def _run() -> list[TaskEvent]:
        with patch(
            "tools.launchpad.core.launcher.shutil.which", return_value="/usr/bin/prime"
        ), patch(
            "tools.launchpad.core.launcher.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=proc),
        ):
            task_id = await launcher.launch_eval(spec, repo_root=tmp_path)
            assert task_id in launcher.list_tasks()
            events: list[TaskEvent] = []
            async for ev in launcher.stream_events(task_id):
                events.append(ev)
            code = await launcher.wait_for(task_id, timeout_s=2.0)
            assert code == 0
            return events

    events = asyncio.run(_run())
    kinds = [e.kind for e in events]
    assert "stdout" in kinds
    assert "stderr" in kinds
    assert kinds[-1] == "finished"
    assert events[-1].payload == {"exit_code": 0}
    lines = [e.payload["line"] for e in events if e.kind == "stdout"]
    assert lines == ["hello", "world"]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_launch_missing_executable_raises(tmp_path: Path) -> None:
    spec = _make_spec()

    async def _run() -> None:
        with patch(
            "tools.launchpad.core.launcher.shutil.which", return_value=None
        ):
            with pytest.raises(FileNotFoundError):
                await launcher.launch_eval(spec, repo_root=tmp_path)

    asyncio.run(_run())


def test_duplicate_label_raises(tmp_path: Path) -> None:
    spec = _make_spec()
    proc = _mock_process(stdout_lines=[], stderr_lines=[], exit_code=0)

    async def _run() -> None:
        with patch(
            "tools.launchpad.core.launcher.shutil.which", return_value="/usr/bin/prime"
        ), patch(
            "tools.launchpad.core.launcher.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=proc),
        ):
            await launcher.launch_eval(spec, repo_root=tmp_path)
            # While first is "live" (label still registered), second should reject.
            proc2 = _mock_process(exit_code=0)
            with patch(
                "tools.launchpad.core.launcher.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=proc2),
            ):
                with pytest.raises(RuntimeError):
                    await launcher.launch_eval(spec, repo_root=tmp_path)

    asyncio.run(_run())


def test_stream_events_unknown_task_id_raises() -> None:
    async def _run() -> None:
        with pytest.raises(KeyError):
            async for _ in launcher.stream_events("nope_0"):
                pass

    asyncio.run(_run())


def test_wait_for_unknown_task_id_raises() -> None:
    async def _run() -> None:
        with pytest.raises(KeyError):
            await launcher.wait_for("nope_0")

    asyncio.run(_run())


def test_stop_task_sends_sigterm(tmp_path: Path) -> None:
    spec = _make_spec(label="long_running")

    # Process that "never exits" until terminate() is called.
    proc = MagicMock()
    proc.stdout = MagicMock()
    proc.stderr = MagicMock()
    proc.returncode = None
    terminated = asyncio.Event()

    async def _readline() -> bytes:
        # Block until termination, then EOF.
        await terminated.wait()
        return b""

    proc.stdout.readline = AsyncMock(side_effect=_readline)
    proc.stderr.readline = AsyncMock(side_effect=_readline)

    async def _wait() -> int:
        await terminated.wait()
        proc.returncode = -signal.SIGTERM
        return -signal.SIGTERM

    proc.wait = AsyncMock(side_effect=_wait)

    def _send_signal(_sig: int) -> None:
        terminated.set()

    proc.send_signal = MagicMock(side_effect=_send_signal)
    proc.terminate = MagicMock(side_effect=lambda: terminated.set())
    proc.kill = MagicMock(side_effect=lambda: terminated.set())

    async def _run() -> None:
        with patch(
            "tools.launchpad.core.launcher.shutil.which", return_value="/usr/bin/prime"
        ), patch(
            "tools.launchpad.core.launcher.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=proc),
        ):
            task_id = await launcher.launch_eval(spec, repo_root=tmp_path)
            assert launcher.stop_task(task_id) is True
            proc.send_signal.assert_called_once_with(signal.SIGTERM)
            code = await launcher.wait_for(task_id, timeout_s=2.0)
            assert code == -signal.SIGTERM

    asyncio.run(_run())
