import pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "environments" / "nethack"))

import numpy as np

from nethack_core import BLSTATS_IDX
from nethack_core import ScoreDepthXPReward, DeltaReward
from nethack_core import NetHackCoreEnv


class _FakeObs:
    def __init__(self, score, depth, xp):
        b = np.zeros(27, dtype=np.int64)
        b[BLSTATS_IDX["score"]] = score
        b[BLSTATS_IDX["depth"]] = depth
        b[BLSTATS_IDX["experience_level"]] = xp
        self.blstats = b


def _expected(obs):
    b = obs.blstats
    return (
        float(b[BLSTATS_IDX["score"]])
        + float(b[BLSTATS_IDX["depth"]]) * 50
        + float(b[BLSTATS_IDX["experience_level"]]) * 50
    )


def test_score_depth_xp_formula():
    m = ScoreDepthXPReward()
    m.reset(_FakeObs(0, 1, 1))
    obs = _FakeObs(100, 2, 3)
    assert m.step(obs) == 100 + 2 * 50 + 3 * 50  # 350


def test_delta_reward_uses_previous_obs():
    m = DeltaReward()
    o1, o2 = _FakeObs(10, 1, 1), _FakeObs(30, 2, 1)
    m.reset(o1)
    # potential(o2) - potential(o1) = (30+100+50) - (10+50+50) = 70
    assert m.step(o2) == 70.0


def test_env_native_step_uses_reward_model():
    env = NetHackCoreEnv(task_name="NetHackScore-v0")
    env.seed(42, 42)
    env.reset()
    obs, reward, terminated, truncated, info = env.step(ord("."))
    assert reward == _expected(obs)
    assert isinstance(reward, float)


def test_env_accepts_custom_reward_model():
    env = NetHackCoreEnv(task_name="NetHackScore-v0", reward_model=DeltaReward())
    env.seed(42, 42)
    env.reset()
    # first step's delta from the reset frame is finite (often 0 early on)
    _, reward, *_ = env.step(ord("."))
    assert isinstance(reward, float)
