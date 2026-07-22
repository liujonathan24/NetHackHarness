"""Tests for the engine-backed env surface (EngineEnv).

Covers the deterministic reset/step loop and the two capabilities the engine
env adds on top of the nle path: snapshot/restore branching and difficulty
tune, all driven through the high-level env API rather than RawEngine directly.
"""
import numpy as np
import pytest

from nethack_core import EngineEnv
from nethack_core import CoreObservation

_LINE = [104, 108, 106, 107, 121, 117, 98, 110]


def test_reset_requires_seed():
    env = EngineEnv()
    with pytest.raises(RuntimeError):
        env.reset()
    env.close()


def test_reset_and_step_shapes():
    env = EngineEnv()
    obs, meta = env.reset(seeds=(42, 42))
    assert isinstance(obs, CoreObservation)
    assert obs.glyphs.shape == (21, 79)
    assert obs.blstats.shape[0] >= 26
    assert meta.seeds == (42, 42)

    obs2, done, info = env.step(106)
    assert isinstance(obs2, CoreObservation)
    assert isinstance(done, bool)
    assert isinstance(info, dict)
    env.close()


def test_determinism_same_seed():
    def run():
        env = EngineEnv()
        env.reset(seeds=(42, 42))
        last = None
        for a in _LINE:
            last, _, _ = env.step(a)
        env.close()
        return last

    a, b = run(), run()
    assert np.array_equal(a.glyphs, b.glyphs)
    assert np.array_equal(a.blstats, b.blstats)


def test_snapshot_restore_branching_via_env():
    env = EngineEnv()
    env.reset(seeds=(42, 42))
    for a in _LINE[:3]:
        env.step(a)
    h = env.snapshot()

    line_a = [107, 121, 117, 98]
    line_b = [110, 104, 108, 106]

    for a in line_a:
        obs_a, _, _ = env.step(a)
    glyphs_a = obs_a.glyphs.copy()

    env.restore(h)
    for a in line_b:
        obs_b, _, _ = env.step(a)
    glyphs_b = obs_b.glyphs.copy()

    # Branches diverge.
    assert not np.array_equal(glyphs_a, glyphs_b)

    # Re-running branch A from the same handle is byte-exact (complete snapshot).
    env.restore(h)
    for a in line_a:
        obs_a2, _, _ = env.step(a)
    assert np.array_equal(obs_a2.glyphs, glyphs_a)
    env.free_snapshot(h)
    env.close()


def test_tune_surface_via_env():
    env = EngineEnv()
    env.reset(seeds=(42, 42))

    # Both the proxy and the convenience methods work.
    assert "hunger_rate_scale" in env.tune.catalog()
    env.tune.set(hunger_rate_scale=2.0)
    assert env.tune.get()["hunger_rate_scale"] == 2.0
    env.set_tune(dmg_to_player_scale=0.0)
    assert env.get_tune()["dmg_to_player_scale"] == 0.0
    env.close()


def test_reveal_map_effect_via_env():
    def visible(reveal):
        env = EngineEnv()
        env.reset(seeds=(42, 42))
        if reveal:
            env.tune.set(reveal_map=1.0)
        obs = None
        for _ in range(5):
            obs, _, _ = env.step(106)
        n = int((obs.chars != ord(" ")).sum())
        env.close()
        return n

    assert visible(True) > visible(False)
