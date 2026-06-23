"""CurriculumEnv — a compressed full-game NetHack curriculum.

The hero (fixed female-neutral Valkyrie, full vision) plays a custom dungeon
ordering instead of the linear dungeon:

    descend:  DoD 1 -> 2 -> 3 --[JUMP + stat upgrade]--> Gehennom 48 -> 49 -> 50
    ascend:   Gehennom 50 -> 49 -> 48 --[JUMP]--> DoD 3 -> 2 -> 1
              --[JUMP]--> Elemental Planes: Earth -> Air -> Fire -> Water -> Astral

So a fresh agent meets the easy intro levels, then the deep end of the game
(with appropriately upgraded stats), then climbs back out through the planes.

Mechanics: the boundary transitions are cross-branch jumps via the engine's
``goto_abs`` (Gehennom and the planes are different dungeon branches that normal
stairs can't reach). The env intercepts the DOWN ('>') and UP ('<') keystrokes
that the descend/ascend skills emit, so existing agents and skills work
unmodified — every '>' advances the curriculum's descent path, every '<' its
ascent path. On the DoD-3 -> Gehennom-48 jump the hero's *stats only* (XP level,
HP, attributes) are raised by sampling :class:`ValkyrieUpgradeModel` at the deep
depth.

This subclasses :class:`NetHackCoreEnv`, so it presents the same env interface
to the skill registry, Go-Explore, Voyager, and the verifiers eval.
"""
from __future__ import annotations

import random
from typing import Optional

from .actions import MiscDirection
from .curriculum_upgrade import ValkyrieUpgradeModel
from .env import CoreObservation, EpisodeMetadata, NetHackCoreEnv

#: Female, neutral, human Valkyrie — the standard NetHack-paper benchmark hero.
VALKYRIE = "Val-hum-neu-fem"

#: Default curriculum seed: its Gehennom reaches absolute depth 50, so the deep
#: segment (48-50) is entirely real. (In the laguna benchmark seed set.)
DEFAULT_SEED = 19

_DOWN = int(MiscDirection.DOWN)  # '>'
_UP = int(MiscDirection.UP)      # '<'

# Plane dlevels within the Elemental Planes branch (astral=1 .. earth=5); the
# curriculum enters at Earth and ascends Earth -> Air -> Fire -> Water -> Astral.
_PLANE_ASCENT = [5, 4, 3, 2, 1]  # Earth, Air, Fire, Water, Astral


class CurriculumEnv(NetHackCoreEnv):
    """NetHackCoreEnv with the compressed curriculum dungeon ordering."""

    def __init__(
        self,
        *,
        shallow_depths: tuple[int, ...] = (1, 2, 3),
        deep_depths: tuple[int, ...] = (48, 49, 50),
        upgrade_artifact: Optional[str] = None,
        reveal_map: bool = True,
        **kwargs,
    ) -> None:
        # Full vision on by default ("lights on"). Merge with any caller tune.
        tune = dict(kwargs.pop("tune", None) or {})
        if reveal_map:
            tune.setdefault("reveal_map", 1.0)
        super().__init__(task_name=kwargs.pop("task_name", "engine"),
                         tune=tune or None, **kwargs)
        self._shallow_depths = tuple(shallow_depths)
        self._deep_depths = tuple(deep_depths)
        self._upgrade_model = ValkyrieUpgradeModel.load(upgrade_artifact)
        # Built at reset() once the dungeon table is known.
        self._descend_map: dict[tuple[int, int], tuple] = {}
        self._ascend_map: dict[tuple[int, int], tuple] = {}
        self._pos: Optional[tuple[int, int]] = None
        self._curr_seed: int = DEFAULT_SEED

    # ----- lifecycle -----

    def reset(
        self,
        *,
        seeds: Optional[tuple[int, int]] = None,
        character: Optional[str] = None,
    ) -> tuple[CoreObservation, EpisodeMetadata]:
        if seeds is None and self._pending_seeds is None:
            seeds = (DEFAULT_SEED, DEFAULT_SEED)
        obs, meta = super().reset(
            seeds=seeds, character=character or VALKYRIE,
        )
        self._curr_seed = (self._current_seeds or (DEFAULT_SEED,))[0]
        self._build_curriculum()
        # The game starts on Dungeons of Doom level 1.
        self._pos = (0, 1)
        return obs, meta

    def _build_curriculum(self) -> None:
        """Resolve (dnum, dlevel) for each curriculum stop and wire the
        descend/ascend transition maps from the live dungeon table."""
        table = self._engine.dungeon_table()
        dod = next(d for d in table if "Dungeons of Doom" in d["name"])
        geh = next(d for d in table if "Gehennom" in d["name"])
        planes = next(d for d in table if "Elemental Planes" in d["name"])

        def geh_stop(depth: int) -> tuple[int, int]:
            return (geh["dnum"], depth - geh["depth_start"] + 1)

        # Curriculum stops, in descent order then continuing up through planes.
        shallow = [(dod["dnum"], d) for d in self._shallow_depths]   # DoD 1,2,3
        deep = [geh_stop(d) for d in self._deep_depths]               # Geh 48,49,50
        planes_stops = [(planes["dnum"], dl) for dl in _PLANE_ASCENT] # Earth..Astral

        # Descent chain: shallow... -> [jump+upgrade] -> deep...
        descend_path = shallow + deep
        self._descend_map.clear()
        for i in range(len(descend_path) - 1):
            cur, nxt = descend_path[i], descend_path[i + 1]
            is_upgrade = (cur == shallow[-1] and nxt == deep[0])
            self._descend_map[cur] = (nxt, is_upgrade)

        # Ascent chain: deep(reversed) -> [jump] -> shallow(reversed) -> [jump] -> planes...
        ascend_path = list(reversed(deep)) + list(reversed(shallow)) + planes_stops
        self._ascend_map.clear()
        for i in range(len(ascend_path) - 1):
            cur, nxt = ascend_path[i], ascend_path[i + 1]
            self._ascend_map[cur] = (nxt, False)

        # Remember the boundary depth where the upgrade is applied.
        self._deep_entry_depth = self._deep_depths[0]

    # ----- the curriculum step -----

    def step(self, action: int) -> tuple[CoreObservation, float, bool, bool, dict]:
        if action == _DOWN:
            return self._curriculum_jump(self._descend_map, "descend")
        if action == _UP:
            return self._curriculum_jump(self._ascend_map, "ascend")
        return super().step(action)

    def _curriculum_jump(self, transition_map, direction):
        """Advance one curriculum stop in ``direction`` via a cross-branch jump.

        At a curriculum boundary (or any stop with a defined next), jump to the
        next stop with goto_abs; apply the stat upgrade on the DoD3->Geh48 step.
        At a dead end (deepest level for descend, top plane for ascend), this is
        a no-op that returns the current observation.
        """
        entry = transition_map.get(self._pos)
        if entry is None:
            # No further curriculum movement this direction (boundary/dead-end).
            obs = self._last_observation
            return obs, 0.0, bool(self._engine.done), False, {
                "curriculum": f"{direction}-noop", "pos": self._pos,
            }
        target, is_upgrade = entry
        dnum, dlevel = target
        obs = self._engine.goto_abs(dnum, dlevel)
        info = {"curriculum": direction, "from": self._pos, "to": target}
        if is_upgrade:
            stats = self._sample_upgrade()
            obs = self._engine.modify(**stats)
            info["upgrade"] = stats
        self._pos = target
        reward = self._reward_model.step(obs)
        self._last_observation = obs
        return obs, reward, bool(self._engine.done), False, info

    def _sample_upgrade(self) -> dict:
        """Sample the stats-only upgrade for the deep-entry depth.

        Deterministic given the episode seed + depth so a curriculum episode is
        reproducible.
        """
        rng = random.Random((self._curr_seed << 8) ^ self._deep_entry_depth)
        return self._upgrade_model.sample(self._deep_entry_depth, rng)

    # ----- introspection (handy for GIFs / tests) -----

    @property
    def curriculum_position(self) -> Optional[tuple[int, int]]:
        """Current (dnum, dlevel) curriculum stop."""
        return self._pos
