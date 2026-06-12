"""Divergent-branch exploration tests for the custom NetHack engine.

EngineEnv.branch(n, reseed=...) takes a snapshot of the current state, then
restores it n times.  With reseed=True it reseeds the ISAAC64 gameplay RNG
AFTER each restore (the fork's nle_set_seed, bound on RawEngine.reseed) so
random-chance events diverge across branches; with reseed=False the snapshot
already captures the RNG, so every branch replays byte-identically.

This exercises the spike result: reseed-after-restore makes continuations
diverge, restore-without-reseed replays identically.
"""
import pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "environments" / "nethack"))
from nethack_core.engine_env import EngineEnv


def test_branch_diverges_with_reseed():
    env = EngineEnv(); env.reset(seeds=(42, 42))
    for _ in range(8):
        env.step(ord("s"))  # search a bit so there's RNG-driven activity nearby
    branches = env.branch(8, reseed=True, horizon=40)
    # each branch is a per-step trace; reseeded branches must not all be identical
    assert len({tuple(b) for b in branches}) >= 2


def test_branch_identical_without_reseed():
    env = EngineEnv(); env.reset(seeds=(42, 42))
    for _ in range(8):
        env.step(ord("s"))
    branches = env.branch(4, reseed=False, horizon=40)
    assert len({tuple(b) for b in branches}) == 1  # no reseed -> identical
