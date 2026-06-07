"""
Tests for the PufferLib-shaped adapter. We test the gym contract only —
no actual PufferLib install (raylib dep is platform-painful).

Run with: uv run pytest tests/test_puffer_env.py -v
"""

from __future__ import annotations

import gymnasium
import numpy as np
import pytest

from nethack_core.env import NetHackCoreEnv
from legacy.puffer_env import make_for_puffer, to_gym_dict_env


def test_wrapper_exposes_dict_observation_and_discrete_action_space():
    env = make_for_puffer("mines_to_minetown")
    assert isinstance(env.action_space, gymnasium.spaces.Discrete)
    assert isinstance(env.observation_space, gymnasium.spaces.Dict)
    env.close()


def test_wrapper_reset_returns_dict_obs():
    env = make_for_puffer("mines_to_minetown")
    obs, info = env.reset(seed=42)
    assert isinstance(obs, dict)
    # Core fields the LM-side relies on.
    for key in ("tty_chars", "chars", "glyphs", "blstats", "message",
                "inv_strs", "inv_letters", "inv_glyphs"):
        assert key in obs, f"missing obs key: {key}"
    env.close()


def test_wrapper_step_returns_5tuple():
    env = make_for_puffer("mines_to_minetown")
    env.reset(seed=42)
    out = env.step(1)  # N
    assert len(out) == 5
    obs, reward, terminated, truncated, info = out
    assert isinstance(obs, dict)
    assert isinstance(reward, float)
    assert isinstance(terminated, bool)
    env.close()


def test_wrapper_is_seed_deterministic_via_gym_api():
    """Calling reset(seed=N) twice yields identical post-reset tty hashes."""
    import hashlib

    def fingerprint(seed: int) -> str:
        env = make_for_puffer("mines_to_minetown")
        obs, _ = env.reset(seed=seed)
        env.close()
        return hashlib.md5(obs["tty_chars"].tobytes()).hexdigest()

    assert fingerprint(7) == fingerprint(7)
    assert fingerprint(7) != fingerprint(8)


def test_to_gym_dict_env_works_on_existing_core_env():
    """The lower-level wrap also works (lets you reuse an open NLE)."""
    core = NetHackCoreEnv(task_name="NetHackScore-v0")
    env = to_gym_dict_env(core)
    obs, _ = env.reset(seed=11)
    assert "tty_chars" in obs
    env.close()
