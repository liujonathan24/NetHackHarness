import pathlib
import sys

sys.path.insert(
    0,
    str(pathlib.Path(__file__).resolve().parents[2] / "environments" / "nethack"),
)

import pytest

from nethack_core.engine_env import EngineEnv
from nethack_core.observations import BLSTATS_IDX


def _bl(obs, name):
    return int(obs.blstats[BLSTATS_IDX[name]])


def test_field_mutations_reflect_in_blstats():
    env = EngineEnv()
    env.reset(seeds=(42, 42))
    obs = env.modify(hp=7, max_hp=99, gold=1234, xp_level=5)
    assert _bl(obs, "hitpoints") == 7 and _bl(obs, "max_hitpoints") == 99
    assert _bl(obs, "gold") == 1234 and _bl(obs, "experience_level") == 5


def test_goto_depth_jumps_level():
    env = EngineEnv()
    env.reset(seeds=(42, 42))
    obs = env.modify(goto_depth=4)
    assert _bl(obs, "depth") == 4


def test_unknown_field_rejected():
    env = EngineEnv()
    env.reset(seeds=(42, 42))
    with pytest.raises(KeyError):
        env.modify(not_a_field=1)


def test_out_of_range_rejected():
    env = EngineEnv()
    env.reset(seeds=(42, 42))
    with pytest.raises(ValueError):
        env.modify(xp_level=999)


def test_at_reset_config():
    env = EngineEnv()
    obs, _ = env.reset(seeds=(42, 42), modify={"hp": 13, "gold": 500})
    assert _bl(obs, "hitpoints") == 13 and _bl(obs, "gold") == 500
