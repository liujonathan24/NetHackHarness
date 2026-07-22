"""
Smoke tests for nethack_core. The reproducibility test is the important one:
if it fails on `main`, we have an entropy leak somewhere.

Run with: uv run pytest tests/ -v
"""

from __future__ import annotations

import pytest

from nethack_core import NetHackCoreEnv


def test_seed_before_reset_enforced():
    env = NetHackCoreEnv(task_name="NetHackScore-v0")
    with pytest.raises(RuntimeError, match="requires seeds"):
        env.reset()


def test_seed_then_reset_works():
    env = NetHackCoreEnv(task_name="NetHackScore-v0")
    env.seed(core=42, disp=42)
    obs, meta = env.reset()
    assert meta.seeds == (42, 42)
    assert obs.tty_chars.shape == (24, 80)


def test_reproducibility_with_same_seed():
    """
    The reason this whole wrapper exists. Two envs with the same seed and
    the same action sequence must produce the same observations and rewards.
    If this test fails, you have an entropy leak.
    """
    actions = [1, 2, 3, 4, 5, 6, 7, 8, 1, 2, 3, 4, 5, 6, 7, 8]

    rewards_a, hashes_a = _run(actions, seed=12345)
    rewards_b, hashes_b = _run(actions, seed=12345)

    assert rewards_a == rewards_b, (
        f"Reward streams diverged between two seeded runs:\n"
        f"  a: {rewards_a}\n  b: {rewards_b}"
    )
    assert hashes_a == hashes_b, "tty_chars diverged between two seeded runs"


def test_different_seeds_produce_different_episodes():
    actions = [1, 2, 3, 4, 5]
    rewards_a, hashes_a = _run(actions, seed=1)
    rewards_b, hashes_b = _run(actions, seed=2)
    assert (rewards_a, hashes_a) != (rewards_b, hashes_b), (
        "Different seeds produced identical episodes -- seeding is broken."
    )


def _run(actions: list[int], seed: int) -> tuple[list[float], list[int]]:
    import hashlib
    env = NetHackCoreEnv(task_name="NetHackScore-v0")
    env.seed(core=seed, disp=seed)
    obs, _ = env.reset()
    rewards = []
    hashes = [int(hashlib.md5(obs.tty_chars.tobytes()).hexdigest()[:8], 16)]
    for a in actions:
        obs, r, term, trunc, _ = env.step(a)
        rewards.append(r)
        hashes.append(int(hashlib.md5(obs.tty_chars.tobytes()).hexdigest()[:8], 16))
        if term or trunc:
            break
    env.close()
    return rewards, hashes
