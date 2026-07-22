"""
legacy.puffer_env
=======================

A PufferLib-shaped adapter over NetHackCoreEnv.

We don't import pufferlib here — it has a system-level raylib build
dependency that's painful on macOS and CI. Instead we expose:

  * `to_gym_dict_env(NetHackCoreEnv) -> gymnasium.Env`  — wraps our env so
    PufferLib's standard gymnasium consumer can take it.
  * `make_for_puffer(tier_name, ...) -> gymnasium.Env`  — convenience
    factory.

The actual speed bottleneck per `tools/profile_env.py` (Day 3 profiling) is
`observations.shape()`, which runs at 3.8k/sec on a single thread. PufferLib's
shared-memory vec gives us ~10× via parallelism, which is why this adapter
exists.

PufferLib install path (NOT done automatically because of raylib):

    # macOS:
    brew install raylib
    # Linux (Debian/Ubuntu):
    apt-get install -y libraylib-dev
    # then:
    uv pip install "pufferlib>=2.0"

Usage with PufferLib:

    from pufferlib.environments.gymnasium import GymnasiumEnvironment
    from legacy.puffer_env import make_for_puffer

    env = make_for_puffer("solo_combat")
    puffer_env = GymnasiumEnvironment(env)
"""

from __future__ import annotations

from typing import Optional

import gymnasium as gym
import numpy as np

from nethack_harness.curriculum.curriculum import TierName, get_tier
from nethack_core import CoreObservation, NetHackCoreEnv


class _GymDictWrapper(gym.Env):
    """
    Wrap NetHackCoreEnv so it presents a Dict observation space + Discrete
    action space + reset()/step() that PufferLib (or any gymnasium consumer)
    can introspect.

    The reason we don't just expose NetHackCoreEnv directly: it requires
    `seed()` before `reset()`, and gymnasium consumers call `reset(seed=N)`
    in one shot. This wrapper bridges that convention.
    """
    metadata = {"render_modes": []}

    def __init__(self, inner: NetHackCoreEnv):
        super().__init__()
        self._inner = inner
        self._obs_space = inner.underlying.observation_space
        self.observation_space = self._obs_space
        self.action_space = inner.action_space

    def reset(self, *, seed: Optional[int] = None, options=None):
        if seed is None:
            # PufferLib will reset many envs simultaneously; we want each one
            # to be deterministic but distinct. Use the env's id as fallback.
            seed = abs(hash(id(self))) % (2**31 - 1)
        self._inner.seed(core=int(seed), disp=int(seed))
        obs, meta = self._inner.reset()
        return _core_obs_to_dict(obs), {"seeds": meta.seeds}

    def step(self, action):
        obs, reward, terminated, truncated, info = self._inner.step(int(action))
        return _core_obs_to_dict(obs), reward, terminated, truncated, info

    def close(self):
        self._inner.close()


def _core_obs_to_dict(obs: CoreObservation) -> dict:
    """CoreObservation dataclass -> dict (the format gymnasium expects)."""
    out = {
        "tty_chars": obs.tty_chars,
        "tty_colors": obs.tty_colors,
        "tty_cursor": obs.tty_cursor,
        "glyphs": obs.glyphs,
        "chars": obs.chars,
        "colors": obs.colors,
        "message": obs.message,
        "inv_strs": obs.inv_strs,
        "inv_letters": obs.inv_letters,
        "inv_glyphs": obs.inv_glyphs,
        "blstats": obs.blstats,
    }
    if obs.misc is not None:
        out["misc"] = obs.misc
    return out


def to_gym_dict_env(inner: NetHackCoreEnv) -> gym.Env:
    """Wrap an existing NetHackCoreEnv as a standard gymnasium Env."""
    return _GymDictWrapper(inner)


def make_for_puffer(tier_name: str, **inner_kwargs) -> gym.Env:
    """Build a gymnasium-shaped env for the given curriculum tier."""
    spec = get_tier(tier_name)
    inner = NetHackCoreEnv(
        task_name=spec.nle_task,
        max_episode_steps=spec.max_episode_steps,
        des_file=spec.des_file,
        **inner_kwargs,
    )
    return to_gym_dict_env(inner)
