"""CurriculumEnv: the compressed curriculum dungeon ordering, the deep-jump
stat upgrade, and the Valkyrie + full-vision defaults."""
import pathlib
import sys

sys.path.insert(
    0,
    str(pathlib.Path(__file__).resolve().parents[2] / "environments" / "nethack"),
)

import numpy as np
import pytest

from nethack_core.actions import MiscDirection
from nethack_core.curriculum_env import CurriculumEnv
from nethack_core.curriculum_upgrade import ValkyrieUpgradeModel
from nethack_core.observations import BLSTATS_IDX

DOWN = int(MiscDirection.DOWN)
UP = int(MiscDirection.UP)


def _b(obs, name):
    return int(obs.blstats[BLSTATS_IDX[name]])


def _fresh():
    env = CurriculumEnv()
    obs, _ = env.reset()
    return env, obs


def test_starts_valkyrie_with_full_vision():
    env, obs = _fresh()
    inv = "\n".join(
        s.tobytes().decode(errors="replace").rstrip("\x00")
        for s in np.array(obs.inv_strs)
    )
    assert "long sword" in inv  # female Valkyrie signature kit
    assert env._tune.get("reveal_map") == 1.0
    assert env.curriculum_position == (0, 1)
    assert _b(obs, "depth") == 1


def test_descend_jumps_from_3_to_48_with_upgrade():
    env, obs = _fresh()
    env.step(DOWN)             # -> DoD 2
    obs, *_ = env.step(DOWN)   # -> DoD 3
    assert _b(obs, "depth") == 3
    obs, _, _, _, info = env.step(DOWN)  # boundary: jump to Gehennom 48 + upgrade
    assert _b(obs, "depth") == 48
    assert _b(obs, "dungeon_number") == 1  # Gehennom
    assert "upgrade" in info
    # Stats jumped up.
    assert _b(obs, "experience_level") >= 12
    assert _b(obs, "max_hitpoints") >= 100
    assert _b(obs, "strength") >= 18


def test_full_descent_reaches_50():
    env, _ = _fresh()
    depths = []
    for _ in range(5):
        obs, *_ = env.step(DOWN)
        depths.append(_b(obs, "depth"))
    assert depths == [2, 3, 48, 49, 50]


def test_ascend_from_48_jumps_to_3_then_planes():
    env, _ = _fresh()
    for _ in range(5):
        env.step(DOWN)  # descend to Gehennom 50
    assert env.curriculum_position == (1, 23)
    seq = []
    for _ in range(10):  # 50->49->48->[3]->2->1->Earth->Air->Fire->Water->Astral
        obs, _, _, _, info = env.step(UP)
        seq.append((int(obs.blstats[BLSTATS_IDX["dungeon_number"]]),
                    env.curriculum_position))
    dnums = [d for d, _ in seq]
    # Climbs Gehennom (1) -> DoD (0) -> Elemental Planes (7).
    assert 0 in dnums and 7 in dnums
    # Last five stops are the five planes (dnum 7, dlevels 5..1).
    assert [pos for _, pos in seq][-5:] == [(7, 5), (7, 4), (7, 3), (7, 2), (7, 1)]


def test_deepest_descent_is_noop():
    env, _ = _fresh()
    for _ in range(5):
        env.step(DOWN)  # at Gehennom 50 (deepest)
    obs, _, _, _, info = env.step(DOWN)
    assert info["curriculum"] == "descend-noop"
    assert _b(obs, "depth") == 50


def test_skill_registry_drives_curriculum():
    """The existing descend/ascend skills (what Go-Explore/Voyager call) drive
    the curriculum jumps — no stair navigation required in the curriculum env."""
    from nethack_core.observations import shape as shape_observation
    from nethack_harness.tools.skills import registry

    env = CurriculumEnv()
    env.reset()
    char = {"role": "Valkyrie"}

    def drive(skill, n):
        for _ in range(n):
            so = shape_observation(env._last_observation, char)
            res = registry.call(skill, env, so)
            for a in res.actions:
                env.step(a)

    drive("descend", 5)  # to Gehennom 50
    assert env.curriculum_position == (1, 23)
    drive("ascend", 10)  # up through DoD into the planes
    assert env.curriculum_position[0] == 7  # Elemental Planes


def test_upgrade_is_deterministic():
    model = ValkyrieUpgradeModel.analytic()
    import random
    a = model.sample(48, random.Random(123))
    b = model.sample(48, random.Random(123))
    assert a == b
    assert a["hp"] == a["max_hp"]  # arrive at full health
