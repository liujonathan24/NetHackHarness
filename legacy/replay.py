"""
legacy.replay
===================

Cheap trajectory record/replay. Because NLE doesn't natively support copy()
or pickling, we record (seeds, action_sequence) per episode and reconstruct
state by replaying actions through a freshly-seeded env.

This is sufficient for:
    * debugging non-reproducible episodes
    * MCTS-style search if you keep the branching factor reasonable
    * exporting trajectories for SFT warmup

It is NOT sufficient for fast O(1) state cloning -- for that you want true
save-state via NetHack's dosave()/dorecover(), which is the stretch goal.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Optional

from nethack_core import NetHackCoreEnv


@dataclass
class TrajectoryFrame:
    """One step of rendered state, captured for the replay viewer.

    Storing this alongside actions costs ~2 KB/step but lets the viewer
    render the timeline without re-executing NLE — which matters because
    NLE compilation isn't always available where the viewer runs (browser,
    Hub dashboard, etc.).
    """
    tty: str                  # rendered 24-row tty with newlines (~1.9 KB)
    message: str
    status: dict
    inventory: list[dict]     # serialized InventoryItem dicts
    reward: float
    action: Optional[int] = None     # the action that produced this frame
    skill: Optional[dict] = None     # {"name": "...", "args": {...}} if known
    journal: Optional[dict] = None   # serialized Journal state


@dataclass
class Trajectory:
    seeds: tuple[int, int]
    task_name: str
    character: Any                  # str (legacy) or dict (preferred)
    actions: list[int]
    rewards: list[float]
    terminated: bool
    truncated: bool
    final_status: dict
    # New in v0.0.2: optional per-step rendering for the viewer.
    frames: list[TrajectoryFrame] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, s: str) -> "Trajectory":
        data = json.loads(s)
        data["seeds"] = tuple(data["seeds"])
        # Re-hydrate frames if present.
        frame_data = data.pop("frames", []) or []
        data["frames"] = [TrajectoryFrame(**f) for f in frame_data]
        return cls(**data)

    def save(self, path: Path) -> None:
        Path(path).write_text(self.to_json())

    @classmethod
    def load(cls, path: Path) -> "Trajectory":
        return cls.from_json(Path(path).read_text())


def _frame_from_obs(obs, reward: float, action: Optional[int] = None,
                    skill: Optional[dict] = None,
                    journal: Optional[dict] = None) -> TrajectoryFrame:
    """Build a TrajectoryFrame from a raw CoreObservation."""
    # Lazy import to avoid a cycle.
    from nethack_core import observations, parse_inventory

    tty = "\n".join("".join(chr(c) for c in row).rstrip() for row in obs.tty_chars)
    msg = bytes(obs.message).split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
    inv = [
        {
            "letter": item.letter,
            "description": item.description,
            "is_worn": item.is_worn,
            "is_wielded": item.is_wielded,
            "is_blessed": item.is_blessed,
        }
        for item in parse_inventory(obs.inv_strs, obs.inv_letters, obs.inv_glyphs)
    ]
    return TrajectoryFrame(
        tty=tty,
        message=msg,
        status=observations.parse_status(obs.blstats),
        inventory=inv,
        reward=reward,
        action=action,
        skill=skill,
        journal=journal,
    )


class TrajectoryRecorder:
    """Wraps a NetHackCoreEnv and records every action, reward, and frame."""

    def __init__(self, env: NetHackCoreEnv, capture_frames: bool = True):
        self.env = env
        self._capture = capture_frames
        self._actions: list[int] = []
        self._rewards: list[float] = []
        self._frames: list[TrajectoryFrame] = []
        self._terminated = False
        self._truncated = False

    def reset(self, **kwargs):
        self._actions = []
        self._rewards = []
        self._frames = []
        self._terminated = False
        self._truncated = False
        obs, meta = self.env.reset(**kwargs)
        if self._capture:
            self._frames.append(_frame_from_obs(obs, reward=0.0))
        return obs, meta

    def step(self, action: int, skill: Optional[dict] = None,
             journal: Optional[dict] = None):
        obs, reward, terminated, truncated, info = self.env.step(action)
        self._actions.append(int(action))
        self._rewards.append(float(reward))
        if self._capture:
            self._frames.append(
                _frame_from_obs(obs, reward=reward, action=int(action),
                                skill=skill, journal=journal)
            )
        self._terminated = terminated
        self._truncated = truncated
        return obs, reward, terminated, truncated, info

    def export(self, final_status: dict, character: Optional[Any] = None) -> Trajectory:
        assert self.env.current_seeds is not None, "Env has no seeds; cannot export."
        return Trajectory(
            seeds=self.env.current_seeds,
            task_name=self.env.task_name,
            character=character,
            actions=self._actions,
            rewards=self._rewards,
            terminated=self._terminated,
            truncated=self._truncated,
            final_status=final_status,
            frames=self._frames,
        )


def replay(trajectory: Trajectory, env: NetHackCoreEnv, until_step: Optional[int] = None):
    """
    Replay a trajectory through a fresh env. Stops at `until_step` if given,
    else plays through the whole recorded action sequence.

    Yields (obs, reward, terminated, truncated, info) tuples so callers can
    drive a UI, audit reproducibility, or fork at a particular step.
    """
    env.seed(*trajectory.seeds)
    obs, meta = env.reset(character=trajectory.character)
    yield obs, 0.0, False, False, {"meta": meta}

    n = len(trajectory.actions) if until_step is None else min(until_step, len(trajectory.actions))
    for i in range(n):
        result = env.step(trajectory.actions[i])
        yield result
        _, _, terminated, truncated, _ = result
        if terminated or truncated:
            break


def audit_reproducibility(trajectory: Trajectory, env: NetHackCoreEnv) -> dict:
    """
    Replay a trajectory and check that the rewards match. Returns a diff
    report. If any step diverges, we've found a source of nondeterminism.

    This is the workhorse for hunting down the entropy leaks discussed in
    the design doc.
    """
    diffs = []
    for i, (obs, reward, terminated, truncated, _) in enumerate(replay(trajectory, env)):
        if i == 0:  # initial obs has no associated recorded reward
            continue
        recorded = trajectory.rewards[i - 1]
        if abs(reward - recorded) > 1e-9:
            diffs.append({
                "step": i - 1,
                "recorded_reward": recorded,
                "replayed_reward": reward,
                "delta": reward - recorded,
            })
    return {
        "trajectory_length": len(trajectory.actions),
        "divergences": diffs,
        "is_reproducible": len(diffs) == 0,
    }
