"""CurriculumPrimitivesEnv — the compressed curriculum at the *harness* layer,
with NO descend/ascend mega-skill.

This is the faithful, no-cheat sibling of :class:`CurriculumEnv`. Where
``CurriculumEnv`` lets the ``descend``/``ascend`` skills teleport across floors
regardless of hero position, this env requires the agent to **navigate to and
stand on a real stair** and press the raw ``>``/``<`` keystroke. The only
internal redirection is the two cross-branch boundary jumps (which ordinary
stairs cannot express), and each fires *only* when the hero genuinely stands on
the boundary stair:

    * on Dungeons-of-Doom level 3's DOWN stair, a real ``>`` jumps to Gehennom
      ``deep_lo`` (and applies the stats-only upgrade);
    * on the deep segment's top (Gehennom ``deep_lo``) UP stair, a real ``<``
      jumps back to DoD level 3.

Every other move/`>`/`<` is handled by the real engine (within-segment descents
and ascents naturally require the hero to be on a stair). So the curriculum is a
compressed 6-floor down / 6-floor up tour (DoD 1-2-3 <-> Gehennom 48-49-50),
reached entirely by primitive navigation.

It subclasses :class:`NetHackCoreEnv` (not ``EngineEnv``) so it presents the
exact interface the verifiers harness/skill-registry consume — 5-tuple ``step``,
``last_observation``, ``observation_keys``, ``modify`` — which the raw
``EngineEnv`` does not. ``NetHackCoreEnv`` already wraps a ``RawEngine`` on its
native path, and ``RawEngine`` exposes ``hero_on_stair``/``goto_abs``/
``dungeon_table``, so the on-stair logic ports directly onto ``self._engine``.

``curriculum_floor(obs)`` maps the absolute dungeon level to curriculum floor
1..6 (DoD 1/2/3 -> 1/2/3; Gehennom deep_lo.. -> 4/5/6); the natural "how deep
into the game" axis the CH loop optimizes.
"""
from __future__ import annotations

import random
from typing import Optional

from .actions import MiscDirection
from .curriculum_upgrade import ValkyrieUpgradeModel
from .env import CoreObservation, EpisodeMetadata, NetHackCoreEnv
from .observations import BLSTATS_IDX

VALKYRIE = "Val-hum-neu-fem"
DEFAULT_SEED = 19  # Gehennom reaches absolute depth 50 here (full 6-floor deep segment)

_DNUM = BLSTATS_IDX["dungeon_number"]
_DEPTH = BLSTATS_IDX["depth"]
_DOWN = int(MiscDirection.DOWN)  # '>'
_UP = int(MiscDirection.UP)      # '<'


class CurriculumPrimitivesEnv(NetHackCoreEnv):
    """NetHackCoreEnv with the compressed curriculum + on-stair boundary jumps.

    No descend/ascend mega-skill: the agent must navigate onto the real stairs.
    """

    #: Starting stat boost applied at reset so the hero survives the early
    #: Dungeons of Doom (the descend/ascend cheat used to dodge this by
    #: teleporting). This isolates the *navigation* challenge from survival:
    #: a tanky, hard-hitting hero that still must find and reach the stairs.
    #: NetHack-encoded: str=125 is STR 25 (exceptional melee); xp_level lifts
    #: to-hit; max_hp/hp give a large survivability buffer.
    DEFAULT_START_STATS = {
        "max_hp": 250, "hp": 250, "str": 125, "dex": 20, "con": 20, "xp_level": 10,
    }

    def __init__(
        self,
        *,
        shallow_depths: tuple[int, ...] = (1, 2, 3),
        deep_depths: tuple[int, ...] = (48, 49, 50),
        upgrade_artifact: Optional[str] = None,
        reveal_map: bool = True,
        start_stats: Optional[dict] = None,
        **kwargs,
    ) -> None:
        # Full vision on by default ("lights on"); merge with any caller tune.
        tune = dict(kwargs.pop("tune", None) or {})
        if reveal_map:
            tune.setdefault("reveal_map", 1.0)
        super().__init__(task_name=kwargs.pop("task_name", "engine"),
                         tune=tune or None, **kwargs)
        self._shallow = tuple(shallow_depths)
        self._deep_req = tuple(deep_depths)
        self._upgrade_model = ValkyrieUpgradeModel.load(upgrade_artifact)
        self._start_stats = (dict(self.DEFAULT_START_STATS) if start_stats is None
                             else dict(start_stats))
        self._curr_seed = DEFAULT_SEED
        # Resolved at reset() from the live dungeon table.
        self._dod_dnum = 0
        self._geh_dnum = 5
        self._geh_start = 28
        self._shallow_hi = 3
        self._deep_lo = 48
        self._deep_hi = 50

    # ----- lifecycle -----

    def reset(
        self,
        *,
        seeds: Optional[tuple[int, int]] = None,
        character: Optional[str] = None,
    ) -> tuple[CoreObservation, EpisodeMetadata]:
        if seeds is None and self._pending_seeds is None:
            seeds = (DEFAULT_SEED, DEFAULT_SEED)
        obs, meta = super().reset(seeds=seeds, character=character or VALKYRIE)
        self._curr_seed = (self._current_seeds or (DEFAULT_SEED,))[0]
        table = self._engine.dungeon_table()
        self._dod_dnum = next(
            d for d in table if "Dungeons of Doom" in d["name"])["dnum"]
        geh = next(d for d in table if "Gehennom" in d["name"])
        self._geh_dnum = geh["dnum"]
        self._geh_start = geh["depth_start"]
        geh_max = geh["depth_start"] + geh["num_dunlevs"] - 1
        # Clamp the deep segment into Gehennom's actual (seed-dependent) range.
        self._deep_lo = max(geh["depth_start"], min(geh_max, self._deep_req[0]))
        self._deep_hi = max(geh["depth_start"], min(geh_max, self._deep_req[-1]))
        self._shallow_hi = max(self._shallow)
        # Apply the starting survivability/attack boost so DoD monster deaths
        # stop and the curriculum tests navigation, not early-game RNG survival.
        if self._start_stats:
            obs = self.modify(**self._start_stats)
        return obs, meta

    # ----- the curriculum step (on-stair boundary jump only) -----

    def step(self, action: int) -> tuple[CoreObservation, float, bool, bool, dict]:
        if action in (_DOWN, _UP):
            # NetHackCoreEnv._engine is an EngineEnv; its `.engine` is the
            # RawEngine that exposes to_core_observation()/hero_on_stair().
            raw = self._engine.engine
            obs0 = raw.to_core_observation()
            dnum = int(obs0.blstats[_DNUM])
            depth = int(obs0.blstats[_DEPTH])
            # +1/-1 on the level's MAIN down/up stair; +2/-2 on the BRANCH
            # staircase (Gnomish Mines entrance). 0 otherwise.
            on_stair = raw.hero_on_stair()

            # DoD levels 2-4 carry the Mines branch entrance (a second '>'); an
            # agent going to the nearest '>' would fall into the Mines and off the
            # curriculum. Handle the two DoD downstairs so the hero stays on the
            # linear DoD 1->2->3->Gehennom path:
            #   * On DoD3, ANY downstair (main==1 or branch==2) jumps to Gehennom.
            #   * On DoD1/2, only the BRANCH stair (==2) is redirected to the next
            #     DoD level; the MAIN stair (==1) descends NORMALLY (untouched), so
            #     ordinary within-DoD descent keeps its real engine behavior.
            if action == _DOWN and dnum == self._dod_dnum:
                if depth == self._shallow_hi and on_stair in (1, 2):
                    self._engine.goto_abs(
                        self._geh_dnum, self._deep_lo - self._geh_start + 1)
                    stats = self._sample_upgrade()
                    obs = self.modify(**stats)  # NetHackCoreEnv.modify updates last_obs
                    reward = self._reward_model.step(obs)
                    return obs, reward, bool(self._engine.done), False, {
                        "curriculum": "jump_down", "to_depth": self._deep_lo,
                        "upgrade": stats,
                    }
                if depth < self._shallow_hi and on_stair == 2:
                    obs = self._engine.goto_abs(self._dod_dnum, depth + 1)
                    self._last_observation = obs
                    reward = self._reward_model.step(obs)
                    return obs, reward, bool(self._engine.done), False, {
                        "curriculum": "dod_descend", "to_depth": depth + 1,
                    }

            # Deep segment top (Gehennom deep_lo) UP stair: real '<' jumps back.
            if (action == _UP and dnum == self._geh_dnum
                    and depth == self._deep_lo and on_stair == -1):
                obs = self._engine.goto_abs(self._dod_dnum, self._shallow_hi)
                self._last_observation = obs
                reward = self._reward_model.step(obs)
                return obs, reward, bool(self._engine.done), False, {
                    "curriculum": "jump_up", "to_depth": self._shallow_hi,
                }

        # Default: the real engine handles the action (incl. within-segment real
        # '>'/'<', which require the hero to actually be on a stair).
        return super().step(action)

    def _sample_upgrade(self) -> dict:
        rng = random.Random((self._curr_seed << 8) ^ self._deep_lo)
        return self._upgrade_model.sample(self._deep_lo, rng)

    # ----- curriculum metric -----

    def curriculum_floor(self, obs) -> int:
        """DoD 1/2/3 -> 1/2/3; Gehennom deep_lo.. -> 4/5/6; else 0."""
        dnum = int(obs.blstats[_DNUM])
        depth = int(obs.blstats[_DEPTH])
        if dnum == self._dod_dnum and 1 <= depth <= 3:
            return depth
        if dnum == self._geh_dnum and depth >= self._deep_lo:
            return 3 + (depth - self._deep_lo + 1)
        return 0
