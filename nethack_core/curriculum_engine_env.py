"""CurriculumEngineEnv — the curriculum at the raw-engine layer (for Go-Explore
/ Voyager, which drive an EngineEnv with primitive keystrokes).

The agent uses ONLY real game commands (move `hjklyubn`, search `s`, and the
real stair commands `>` / `<`). There is NO descend/ascend skill. The
cross-branch jump is purely internal: the agent descends the real stairs as
normal, and the env transparently redirects at the two segment boundaries:

    * descend the real `>` past Dungeons-of-Doom level 3  → jump to Gehennom 48
      (and apply the stats-only upgrade), so a real descent from DoD 3 lands deep.
    * ascend the real `<` above Gehennom 48               → jump back to DoD 3.

So the curriculum is a compressed 6-floor down / 6-floor up tour
(DoD 1-2-3  <->  Gehennom 48-49-50), reached entirely by the agent navigating to
and using the real stairs — the descend/ascend mechanism is only ever used
internally for the 3<->48 transition.

``curriculum_floor(obs)`` maps the absolute dungeon level to the curriculum
floor 1..6 (DoD 1/2/3 -> 1/2/3; Gehennom 48/49/50 -> 4/5/6), the natural "how
deep into the game" axis for the experiments.
"""
from __future__ import annotations

import random
from typing import Optional

from .actions import MiscDirection
from .curriculum_upgrade import ValkyrieUpgradeModel
from .engine_env import EngineEnv
from .observations import BLSTATS_IDX

VALKYRIE = "Val-hum-neu-fem"
DEFAULT_SEED = 19  # Gehennom reaches absolute depth 50 here (full 6-floor deep segment)

_DNUM = BLSTATS_IDX["dungeon_number"]
_DEPTH = BLSTATS_IDX["depth"]
_DOWN = int(MiscDirection.DOWN)  # '>'
_UP = int(MiscDirection.UP)      # '<'


class CurriculumEngineEnv(EngineEnv):
    """EngineEnv with the compressed 6-down/6-up curriculum + internal jumps."""

    def __init__(
        self,
        *,
        shallow_depths: tuple[int, ...] = (1, 2, 3),
        deep_depths: tuple[int, ...] = (48, 49, 50),
        upgrade_artifact: Optional[str] = None,
        character: str = VALKYRIE,
        reveal_map: bool = True,
    ) -> None:
        super().__init__()
        self._shallow = tuple(shallow_depths)
        self._deep_req = tuple(deep_depths)
        self._character = character
        self._reveal = reveal_map
        self._upgrade_model = ValkyrieUpgradeModel.load(upgrade_artifact)
        self._seed_used = DEFAULT_SEED
        # Resolved at reset() from the live dungeon table.
        self._dod_dnum = 0
        self._geh_dnum = 1
        self._geh_start = 28
        self._shallow_hi = 3
        self._deep_lo = 48
        self._deep_hi = 50

    # ----- lifecycle -----

    def reset(self, *, seeds=None, **_ignored):
        if seeds is None and self._pending_seeds is None:
            seeds = (DEFAULT_SEED, DEFAULT_SEED)
        tune = {"reveal_map": 1.0} if self._reveal else None
        obs, meta = super().reset(seeds=seeds, tune=tune, character=self._character)
        self._seed_used = (self._current_seeds or (DEFAULT_SEED,))[0]
        table = self.dungeon_table()
        self._dod_dnum = next(d for d in table if "Dungeons of Doom" in d["name"])["dnum"]
        geh = next(d for d in table if "Gehennom" in d["name"])
        self._geh_dnum = geh["dnum"]
        self._geh_start = geh["depth_start"]
        geh_max = geh["depth_start"] + geh["num_dunlevs"] - 1
        # Clamp the deep segment into Gehennom's actual (seed-dependent) range.
        self._deep_lo = max(geh["depth_start"], min(geh_max, self._deep_req[0]))
        self._deep_hi = max(geh["depth_start"], min(geh_max, self._deep_req[-1]))
        self._shallow_hi = max(self._shallow)
        return obs, meta

    # ----- the curriculum step (internal boundary jump, pre-step) -----

    def step(self, action: int):
        """Step the real engine, but at the two segment boundaries redirect a
        REAL stair use (the hero standing on the boundary stair and pressing
        `>`/`<`) into the internal cross-branch jump. The agent never gets a
        descend/ascend skill; it must navigate onto the stairs itself.
        """
        if action in (_DOWN, _UP):
            obs0 = self._engine.to_core_observation()
            dnum = int(obs0.blstats[_DNUM])
            depth = int(obs0.blstats[_DEPTH])
            on_stair = self._engine.hero_on_stair()  # +1 down, -1 up, 0 none

            # On DoD level 3's down stair, a real `>` jumps to the deep segment
            # (Gehennom) and applies the stats-only upgrade.
            if (action == _DOWN and dnum == self._dod_dnum
                    and depth == self._shallow_hi and on_stair == 1):
                self.goto_abs(self._geh_dnum, self._deep_lo - self._geh_start + 1)
                obs = self.modify(**self._sample_upgrade())
                return obs, self.done, {"curriculum": "jump_down", "to_depth": self._deep_lo}

            # On the deep segment's top (Gehennom deep_lo) up stair, a real `<`
            # jumps back to DoD level 3.
            if (action == _UP and dnum == self._geh_dnum
                    and depth == self._deep_lo and on_stair == -1):
                obs = self.goto_abs(self._dod_dnum, self._shallow_hi)
                return obs, self.done, {"curriculum": "jump_up", "to_depth": self._shallow_hi}

        # Default: the real engine handles the action (incl. within-segment
        # real `>`/`<` descents/ascents, which require the hero to be on a stair).
        return super().step(action)

    def _sample_upgrade(self) -> dict:
        rng = random.Random((self._seed_used << 8) ^ self._deep_lo)
        return self._upgrade_model.sample(self._deep_lo, rng)

    # ----- curriculum metric -----

    def curriculum_floor(self, obs) -> int:
        """Map the absolute dungeon level to curriculum floor 1..6 (0 if off-path)."""
        return curriculum_floor_of(obs, self._dod_dnum, self._geh_dnum, self._deep_lo)


def curriculum_floor_of(obs, dod_dnum: int, geh_dnum: int, deep_lo: int) -> int:
    """DoD 1/2/3 -> 1/2/3; Gehennom deep_lo.. -> 4/5/6; else 0."""
    dnum = int(obs.blstats[_DNUM])
    depth = int(obs.blstats[_DEPTH])
    if dnum == dod_dnum and 1 <= depth <= 3:
        return depth
    if dnum == geh_dnum and depth >= deep_lo:
        return 3 + (depth - deep_lo + 1)
    return 0
