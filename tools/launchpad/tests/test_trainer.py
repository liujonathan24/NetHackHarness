"""Tests for `tools.launchpad.core.trainer`.

No real subprocess calls — `asyncio.create_subprocess_exec` is patched to
return a fake process whose stdout/stderr are pre-seeded StreamReaders.
"""

from __future__ import annotations

import asyncio
import functools
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

import pytest

from tools.launchpad.core import trainer
from tools.launchpad.types import (
    RLEvalSpec,
    RLHparams,
    TrainSpec,
)


def _async_test(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Run an async coroutine test via asyncio.run (no plugin required)."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(fn(*args, **kwargs))

    return wrapper


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeProcess:
    """Mimics the subset of asyncio.subprocess.Process we touch."""

    def __init__(self, stdout_lines: list[bytes], stderr_lines: list[bytes] | None = None):
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        for line in stdout_lines:
            self.stdout.feed_data(line)
        self.stdout.feed_eof()
        for line in stderr_lines or []:
            self.stderr.feed_data(line)
        self.stderr.feed_eof()
        self.returncode: int | None = None
        self._terminated = False
        self._killed = False
        self._exit_event = asyncio.Event()

    async def wait(self) -> int:
        await self._exit_event.wait()
        return self.returncode if self.returncode is not None else 0

    def finish(self, code: int = 0) -> None:
        self.returncode = code
        self._exit_event.set()

    def terminate(self) -> None:
        self._terminated = True
        self.finish(code=143)

    def kill(self) -> None:
        self._killed = True
        self.finish(code=-9)


def _reset_registry() -> None:
    trainer._TASKS.clear()


@pytest.fixture(autouse=True)
def _clean_registry():
    _reset_registry()
    yield
    _reset_registry()


# ---------------------------------------------------------------------------
# materialize_rl_toml
# ---------------------------------------------------------------------------


def test_materialize_rl_toml_writes_atomic_and_includes_fields(tmp_path: Path) -> None:
    spec = TrainSpec(
        mode="rl",
        label="exp-test",
        harness="default",
        base_model="meta-llama/Llama-3.2-1B",
        tiers=["scout", "descent"],
        hparams=RLHparams(lr=2e-6, batch_size=32),
        eval=RLEvalSpec(every_steps=100, n_examples=8, tiers=["scout"]),
    )
    dest = tmp_path / "out" / "rl.toml"
    result = trainer.materialize_rl_toml(spec, dest)

    assert result == dest
    assert dest.exists()
    text = dest.read_text()
    assert 'label = "exp-test"' in text
    assert 'base = "meta-llama/Llama-3.2-1B"' in text
    assert "lr = 2e-06" in text
    assert "batch_size = 32" in text
    assert '"scout"' in text
    assert "every_steps = 100" in text


def test_materialize_rl_toml_rejects_wrong_mode(tmp_path: Path) -> None:
    spec = TrainSpec(
        mode="gepa",
        label="x",
        proposer_model="m",
    )
    with pytest.raises(ValueError, match="mode='rl'"):
        trainer.materialize_rl_toml(spec, tmp_path / "x.toml")


def test_materialize_rl_toml_requires_base_model(tmp_path: Path) -> None:
    spec = TrainSpec(mode="rl", label="x", hparams=RLHparams())
    with pytest.raises(ValueError, match="base_model"):
        trainer.materialize_rl_toml(spec, tmp_path / "x.toml")


def test_materialize_rl_toml_requires_hparams(tmp_path: Path) -> None:
    spec = TrainSpec(mode="rl", label="x", base_model="m")
    with pytest.raises(ValueError, match="hparams"):
        trainer.materialize_rl_toml(spec, tmp_path / "x.toml")


# ---------------------------------------------------------------------------
# launch_rl (happy path with mocked subprocess)
# ---------------------------------------------------------------------------


@_async_test
async def test_launch_rl_spawns_and_streams_metrics(tmp_path: Path) -> None:
    lines = [
        b"INFO: starting training\n",
        b"step=1 loss=2.5 kl=0.01\n",
        b"step=2 loss=2.3 kl=0.02 eval/scout=0.4\n",
    ]
    fake = _FakeProcess(stdout_lines=lines)

    async def _fake_exec(*args: Any, **kwargs: Any) -> _FakeProcess:
        return fake

    spec = TrainSpec(
        mode="rl",
        label="t1",
        base_model="m",
        hparams=RLHparams(),
    )

    with patch.object(trainer.shutil, "which", return_value="/usr/bin/prime"), \
         patch("asyncio.create_subprocess_exec", _fake_exec):
        task_id = await trainer.launch_rl(spec, tmp_path)

    assert task_id.startswith("t1_")
    assert task_id in trainer._TASKS

    # Collect metrics until subprocess closes.
    async def _consume() -> list:
        out = []
        async for m in trainer.stream_metrics(task_id):
            out.append(m)
        return out

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0.05)
    fake.finish(code=0)
    metrics = await asyncio.wait_for(consumer, timeout=2.0)

    names = [(m.step, m.name, m.value) for m in metrics]
    assert (1, "loss", 2.5) in names
    assert (1, "kl", 0.01) in names
    assert (2, "loss", 2.3) in names
    assert (2, "eval/scout", 0.4) in names


@_async_test
async def test_launch_rl_wrong_mode_raises(tmp_path: Path) -> None:
    spec = TrainSpec(mode="gepa", label="x", proposer_model="m")
    with pytest.raises(ValueError, match="mode='rl'"):
        await trainer.launch_rl(spec, tmp_path)


@_async_test
async def test_launch_rl_missing_prime_raises(tmp_path: Path) -> None:
    spec = TrainSpec(mode="rl", label="x", base_model="m", hparams=RLHparams())
    with patch.object(trainer.shutil, "which", return_value=None):
        with pytest.raises(FileNotFoundError):
            await trainer.launch_rl(spec, tmp_path)


# ---------------------------------------------------------------------------
# launch_gepa
# ---------------------------------------------------------------------------


@_async_test
async def test_launch_gepa_builds_expected_argv(tmp_path: Path) -> None:
    fake = _FakeProcess(stdout_lines=[b"GEPA starting\n"])
    captured_argv: list[str] = []

    async def _fake_exec(*args: Any, **kwargs: Any) -> _FakeProcess:
        captured_argv.extend(args)
        return fake

    spec = TrainSpec(
        mode="gepa",
        label="g1",
        proposer_model="gpt-4o-mini",
        population=2,
        generations=3,
        eval=RLEvalSpec(n_examples=5),
    )

    with patch.object(trainer.shutil, "which", return_value="/usr/bin/prime"), \
         patch("asyncio.create_subprocess_exec", _fake_exec):
        task_id = await trainer.launch_gepa(spec, tmp_path)

    fake.finish(0)
    assert task_id.startswith("g1_")
    assert "gepa" in captured_argv and "run" in captured_argv
    assert "nethack" in captured_argv
    # max-calls = population * generations = 6
    idx = captured_argv.index("--max-calls")
    assert captured_argv[idx + 1] == "6"
    idx = captured_argv.index("--num-train")
    assert captured_argv[idx + 1] == "5"
    idx = captured_argv.index("--model")
    assert captured_argv[idx + 1] == "gpt-4o-mini"


@_async_test
async def test_launch_gepa_wrong_mode_raises(tmp_path: Path) -> None:
    spec = TrainSpec(mode="rl", label="x", base_model="m", hparams=RLHparams())
    with pytest.raises(ValueError, match="mode='gepa'"):
        await trainer.launch_gepa(spec, tmp_path)


# ---------------------------------------------------------------------------
# stream_metrics / stream_events edge cases
# ---------------------------------------------------------------------------


@_async_test
async def test_stream_metrics_unknown_task_id_raises() -> None:
    with pytest.raises(KeyError):
        async for _ in trainer.stream_metrics("nonexistent"):
            break


@_async_test
async def test_stream_events_unknown_task_id_raises() -> None:
    with pytest.raises(KeyError):
        async for _ in trainer.stream_events("nonexistent"):
            break


@_async_test
async def test_stream_events_emits_stdout_stderr_and_finished(tmp_path: Path) -> None:
    fake = _FakeProcess(
        stdout_lines=[b"hello\n"],
        stderr_lines=[b"warning: x\n"],
    )

    async def _fake_exec(*args: Any, **kwargs: Any) -> _FakeProcess:
        return fake

    spec = TrainSpec(mode="rl", label="evt", base_model="m", hparams=RLHparams())
    with patch.object(trainer.shutil, "which", return_value="/usr/bin/prime"), \
         patch("asyncio.create_subprocess_exec", _fake_exec):
        task_id = await trainer.launch_rl(spec, tmp_path)

    async def _consume() -> list:
        out = []
        async for e in trainer.stream_events(task_id):
            out.append(e)
        return out

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0.05)
    fake.finish(0)
    events = await asyncio.wait_for(consumer, timeout=2.0)

    kinds = [e.kind for e in events]
    assert "stdout" in kinds
    assert "stderr" in kinds
    assert kinds[-1] == "finished"
    assert events[-1].payload["exit_code"] == 0


# ---------------------------------------------------------------------------
# stop_task
# ---------------------------------------------------------------------------


@_async_test
async def test_stop_task_sends_terminate(tmp_path: Path) -> None:
    fake = _FakeProcess(stdout_lines=[b"running\n"])

    async def _fake_exec(*args: Any, **kwargs: Any) -> _FakeProcess:
        return fake

    spec = TrainSpec(mode="rl", label="kill", base_model="m", hparams=RLHparams())
    with patch.object(trainer.shutil, "which", return_value="/usr/bin/prime"), \
         patch("asyncio.create_subprocess_exec", _fake_exec):
        task_id = await trainer.launch_rl(spec, tmp_path)

    assert trainer.stop_task(task_id) is True
    assert fake._terminated is True
    # Drain background tasks.
    await asyncio.sleep(0.05)


def test_stop_task_unknown_returns_false() -> None:
    assert trainer.stop_task("nope") is False
