"""
Tests for replay.py — Trajectory serialization, frame capture, replay loop,
and the audit_reproducibility helper.

Run with: uv run pytest tests/test_replay.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nethack_core.env import NetHackCoreEnv
from legacy.replay import (
    Trajectory,
    TrajectoryFrame,
    TrajectoryRecorder,
    audit_reproducibility,
    replay,
)


def _build_trivial_trajectory(tmp_path: Path) -> Trajectory:
    """Build a synthetic trajectory with one frame; the cheapest schema check."""
    frame = TrajectoryFrame(
        tty="@.....", message="hi", status={"hitpoints": 10},
        inventory=[], reward=0.0,
    )
    return Trajectory(
        seeds=(1, 2),
        task_name="NetHackScore-v0",
        character={"role": "monk"},
        actions=[],
        rewards=[],
        terminated=False,
        truncated=False,
        final_status={},
        frames=[frame],
    )


# ---------- serialization ----------

def test_trajectory_roundtrips_through_json(tmp_path):
    """Save → load preserves seeds (as tuple), character, frames."""
    traj = _build_trivial_trajectory(tmp_path)
    out = tmp_path / "traj.json"
    traj.save(out)
    loaded = Trajectory.load(out)
    assert loaded.seeds == (1, 2)
    assert loaded.character == {"role": "monk"}
    assert len(loaded.frames) == 1
    assert isinstance(loaded.frames[0], TrajectoryFrame)
    assert loaded.frames[0].tty == "@....."


def test_trajectory_handles_missing_frames_field_in_legacy_json(tmp_path):
    """Older recordings (pre-Day-3) have no frames key. Must still load."""
    raw = """{
        "seeds": [3, 4],
        "task_name": "NetHackScore-v0",
        "character": null,
        "actions": [1, 2, 3],
        "rewards": [0.0, 0.0, 0.0],
        "terminated": true,
        "truncated": false,
        "final_status": {}
    }"""
    out = tmp_path / "legacy.json"
    out.write_text(raw)
    loaded = Trajectory.load(out)
    assert loaded.actions == [1, 2, 3]
    assert loaded.frames == []


# ---------- live recording ----------

def _make_env() -> NetHackCoreEnv:
    return NetHackCoreEnv(task_name="NetHackScore-v0")


def test_recorder_captures_frames_by_default():
    """First frame is the post-reset state; subsequent frames are per-step."""
    env = _make_env()
    rec = TrajectoryRecorder(env)
    rec.reset(seeds=(7, 7))
    # Three small steps (the action ids are task-action indices, 1..4 are the
    # 4 cardinal directions in NetHackScore's action list).
    for a in [1, 2, 3]:
        _, _, term, trunc, _ = rec.step(a)
        if term or trunc:
            break
    traj = rec.export(final_status={}, character={"role": "monk"})
    # 1 initial frame + 3 step frames.
    assert len(traj.frames) == 4
    assert traj.frames[0].action is None
    assert traj.frames[1].action == 1


def test_recorder_with_capture_disabled_has_no_frames():
    """Opt-out path for cases where frame capture would balloon JSON size."""
    env = _make_env()
    rec = TrajectoryRecorder(env, capture_frames=False)
    rec.reset(seeds=(7, 7))
    rec.step(1)
    traj = rec.export(final_status={}, character=None)
    assert traj.frames == []
    assert traj.actions == [1]


# ---------- replay and audit ----------

def test_replay_yields_initial_then_steps():
    env = _make_env()
    rec = TrajectoryRecorder(env)
    rec.reset(seeds=(11, 11))
    for a in [1, 2]:
        rec.step(a)
    traj = rec.export(final_status={}, character=None)

    fresh = _make_env()
    out = list(replay(traj, fresh))
    # 1 initial + 2 step outputs.
    assert len(out) == 3
    fresh.close()


def test_audit_reproducibility_is_clean_after_record_replay():
    env = _make_env()
    rec = TrajectoryRecorder(env)
    rec.reset(seeds=(13, 13))
    for a in [1, 2, 1, 2, 1]:
        _, _, term, trunc, _ = rec.step(a)
        if term or trunc:
            break
    traj = rec.export(final_status={}, character=None)

    fresh = _make_env()
    audit = audit_reproducibility(traj, fresh)
    assert audit["is_reproducible"] is True
    assert audit["divergences"] == []
    fresh.close()
