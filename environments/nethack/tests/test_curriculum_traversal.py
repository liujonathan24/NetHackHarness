"""Curriculum traversal: cross-branch goto_abs, dungeon table, attribute
injection, and the female-neutral-Valkyrie character preset.

These lock in the engine primitives the curriculum-learning change depends on.
Seed 19 is used because its Gehennom reaches absolute depth 50, so the deep
curriculum segment (47-50) is entirely real.
"""
import pathlib
import sys

sys.path.insert(
    0,
    str(pathlib.Path(__file__).resolve().parents[2] / "environments" / "nethack"),
)

import numpy as np
import pytest

from nethack_core import EngineEnv
from nethack_core import NetHackCoreEnv
from nethack_core import BLSTATS_IDX

CURRICULUM_SEED = 19  # Gehennom reaches absolute depth 50 at this seed.


def _bl(obs, name):
    return int(obs.blstats[BLSTATS_IDX[name]])


def _dungeon(env, needle):
    return next(d for d in env.dungeon_table() if needle in d["name"])


def test_dungeon_table_exposes_gehennom_and_planes():
    env = EngineEnv()
    env.reset(seeds=(CURRICULUM_SEED, CURRICULUM_SEED))
    table = env.dungeon_table()
    names = [d["name"] for d in table]
    assert any("Dungeons of Doom" in n for n in names)
    geh = _dungeon(env, "Gehennom")
    planes = _dungeon(env, "Elemental Planes")
    # Gehennom is a deep branch; its bottom reaches >= depth 50 on this seed.
    assert geh["depth_start"] + geh["num_dunlevs"] - 1 >= 50
    assert planes["num_dunlevs"] == 6  # astral/water/fire/air/earth/dummy


@pytest.mark.parametrize("target_depth", [47, 48, 49, 50])
def test_goto_abs_reaches_deep_gehennom(target_depth):
    env = EngineEnv()
    env.reset(seeds=(CURRICULUM_SEED, CURRICULUM_SEED), tune={"reveal_map": 1.0})
    geh = _dungeon(env, "Gehennom")
    dlevel = target_depth - geh["depth_start"] + 1
    obs = env.goto_abs(geh["dnum"], dlevel)
    assert _bl(obs, "depth") == target_depth
    assert _bl(obs, "dungeon_number") == geh["dnum"]
    # A real, generated floor (not an empty/blank level) under full vision.
    assert int((np.array(obs.chars) != ord(" ")).sum()) > 100
    # The hero is alive and the level is steppable (no crash).
    _, done, _ = env.step(ord("s"))
    assert not done


def test_goto_abs_reaches_plane_of_earth():
    env = EngineEnv()
    env.reset(seeds=(CURRICULUM_SEED, CURRICULUM_SEED), tune={"reveal_map": 1.0})
    planes = _dungeon(env, "Elemental Planes")
    # Earth is dlevel 5 (astral=1, water=2, fire=3, air=4, earth=5, dummy=6).
    obs = env.goto_abs(planes["dnum"], 5)
    assert _bl(obs, "dungeon_number") == planes["dnum"]
    _, done, _ = env.step(ord("s"))
    assert not done


def test_goto_abs_rejects_out_of_range():
    env = EngineEnv()
    env.reset(seeds=(CURRICULUM_SEED, CURRICULUM_SEED))
    geh = _dungeon(env, "Gehennom")
    with pytest.raises(ValueError):
        env.goto_abs(geh["dnum"], geh["num_dunlevs"] + 1)


def test_attribute_injection_round_trips():
    env = EngineEnv()
    env.reset(seeds=(CURRICULUM_SEED, CURRICULUM_SEED))
    obs = env.modify(str=21, dex=18, con=18, int=12, wis=14, cha=16)
    # str=21 is NetHack's encoding for 18/03 (stored raw in the 3..125 field).
    assert _bl(obs, "strength") == 21
    assert _bl(obs, "dexterity") == 18
    assert _bl(obs, "constitution") == 18
    assert _bl(obs, "intelligence") == 12
    assert _bl(obs, "wisdom") == 14
    assert _bl(obs, "charisma") == 16


def test_modify_rejects_out_of_range_attribute():
    env = EngineEnv()
    env.reset(seeds=(CURRICULUM_SEED, CURRICULUM_SEED))
    with pytest.raises(ValueError):
        env.modify(dex=99)  # dex bound is 3..25


def test_valkyrie_character_preset():
    env = EngineEnv()
    obs, _ = env.reset(
        seeds=(CURRICULUM_SEED, CURRICULUM_SEED), character="Val-hum-neu-fem"
    )
    inv = "\n".join(
        s.tobytes().decode(errors="replace").rstrip("\x00")
        for s in np.array(obs.inv_strs)
    )
    # The female Valkyrie starts with the signature long sword + small shield.
    assert "long sword" in inv
    assert "small shield" in inv


def test_reveal_map_reaches_tty_chars():
    """reveal_map must reveal tty_chars (what the agent's map renderer reads),
    not only chars/glyphs. Default (reveal off) leaves tty_chars unchanged."""
    def tty_map_nonblank(reveal):
        env = EngineEnv()
        obs, _ = env.reset(
            seeds=(CURRICULUM_SEED, CURRICULUM_SEED), tune={"reveal_map": reveal}
        )
        obs, _, _ = env.step(ord("."))
        tty = np.array(obs.tty_chars).reshape(24, 80)
        return int((tty[1:22, :] != ord(" ")).sum())

    off = tty_map_nonblank(0.0)
    on = tty_map_nonblank(1.0)
    assert on > off  # full vision reveals far more of the level in the tty map


def test_core_env_threads_character():
    env = NetHackCoreEnv(task_name="engine")
    obs, meta = env.reset(
        seeds=(CURRICULUM_SEED, CURRICULUM_SEED), character="Val-hum-neu-fem"
    )
    assert meta.character == "Val-hum-neu-fem"
    inv = "\n".join(
        s.tobytes().decode(errors="replace").rstrip("\x00")
        for s in np.array(obs.inv_strs)
    )
    assert "long sword" in inv
