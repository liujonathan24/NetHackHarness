"""
GATE C1 — NetHackCoreEnv native backend cutover.

Asserts that NetHackCoreEnv drives the fork engine (via EngineEnv) for NATIVE
tasks (NetHackScore-v0 / NetHackChallenge-v0) while preserving the public
surface: seed-before-reset discipline, the (CoreObservation, EpisodeMetadata)
reset return, and the gym 5-tuple step return.
"""

import pathlib
import sys

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "environments" / "nethack")
)
from nethack_core import NetHackCoreEnv  # noqa: E402


def test_native_env_runs_on_engine():
    env = NetHackCoreEnv(task_name="NetHackScore-v0")
    env.seed(42, 42)
    obs, meta = env.reset()
    assert obs.chars.shape == (21, 79)
    obs2, reward, terminated, truncated, info = env.step(ord("."))
    assert obs2.blstats is not None
    assert isinstance(terminated, bool) and isinstance(truncated, bool)
    env.close()


def test_native_env_is_deterministic():
    def run():
        e = NetHackCoreEnv(task_name="NetHackScore-v0")
        e.seed(7, 7)
        e.reset()
        out = [bytes(e.step(ord("j"))[0].chars.tobytes()) for _ in range(5)]
        e.close()
        return out

    assert run() == run()


def test_no_seed_raises():
    import pytest

    env = NetHackCoreEnv(task_name="NetHackScore-v0")
    with pytest.raises(RuntimeError):
        env.reset()
