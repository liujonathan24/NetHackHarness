"""
nethack_core.env
================

Interface-agnostic wrapper around the NetHack Learning Environment.

Goals:
    * Force deterministic seeding by default (reseed=False, both core and disp).
    * Enforce seed-before-reset.
    * Surface a clean dict observation that downstream layers can shape further.
    * Stay gymnasium-compatible so PufferLib / Sample Factory / scripts work.

This module deliberately does NOT do skill compilation, menu parsing, or
chat-shaping. Those live in sibling modules (skills.py, observations.py).
"""

from __future__ import annotations

import hashlib
import logging
import pathlib
from dataclasses import dataclass, field
from typing import Any, Optional, Union

import numpy as np

# `.rewards` is imported lazily inside __init__: rewards -> observations -> env
# (for CoreObservation), so a module-scope import here would be circular.

# NOTE: `gymnasium`, `nle` and `minihack` are NOT imported at module scope. The
# native engine path (NetHackScore / NetHackChallenge driven by EngineEnv) needs
# none of them. They are imported lazily only in the MiniHack/des_file gym path
# (retired in the curriculum migration) and in `action_space` (PufferLib compat).

logger = logging.getLogger(__name__)


@dataclass
class CoreObservation:
    """Raw observation from the underlying NLE, before any harness processing."""
    tty_chars: np.ndarray       # (24, 80) uint8
    tty_colors: np.ndarray      # (24, 80) uint8
    tty_cursor: np.ndarray      # (2,) int
    glyphs: np.ndarray          # (21, 79) int16
    chars: np.ndarray           # (21, 79) uint8
    colors: np.ndarray          # (21, 79) uint8
    message: np.ndarray         # (256,) uint8 -- last game message
    inv_strs: np.ndarray        # (55, 80) uint8 -- inventory text
    inv_letters: np.ndarray     # (55,) uint8 -- inventory letters
    inv_glyphs: np.ndarray      # (55,) int16
    blstats: np.ndarray         # (26 or 27,) int -- HP, AC, hunger, dlvl, ... (27 on fork engine: NLE_BLSTATS_SIZE=27)
    misc: Optional[np.ndarray] = None  # (3,) -- input-mode flags; not on MiniHack

    @classmethod
    def from_nle(cls, obs: dict[str, np.ndarray]) -> "CoreObservation":
        return cls(**{f.name: obs[f.name] for f in cls.__dataclass_fields__.values() if f.name in obs})


@dataclass
class EpisodeMetadata:
    """Per-rollout metadata. Useful for debugging non-reproducibility."""
    seeds: tuple[int, int]                # (core, disp)
    seed_hash: str
    task_name: str
    character: Optional[str] = None       # e.g. "valkyrie-dwarf-female-lawful"
    extra: dict[str, Any] = field(default_factory=dict)


class NetHackCoreEnv:
    """
    Interface-agnostic NetHack env. Wraps an NLE gym env with:

    * Forced reseed=False
    * Seed-before-reset enforcement
    * Dict observation in our canonical shape
    * Episode metadata logging

    Subsequent layers (skills, observations.py shaping, the verifiers env) treat
    this as their substrate.

    Why `NetHackScore-v0` is the default (not `NetHackChallenge-v0`):
        NetHackChallenge monkey-patches `nethack.set_initial_seeds` at __init__
        (see nle/env/tasks.py:345) to raise on any seed change. That intentional
        anti-TAS hardening makes reproducibility impossible. NetHackScore (the
        parent class) leaves seeding alone, so we use it as the substrate and
        get deterministic episodes for free.

    TODO(jonathan):
        - swap to MiniHack envs when curriculum.py says so
        - support optional `dosave`/`dorecover` save-state (stretch)
        - hook in C-side RNG tracing (rn2_trace) once the patch lands
    """

    def __init__(
        self,
        task_name: str = "NetHackScore-v0",
        max_episode_steps: Optional[int] = None,
        observation_keys: Optional[tuple[str, ...]] = None,
        no_progress_timeout: int = 10_000,
        des_file: Optional[str] = None,
        level_blob: Optional[Union[str, pathlib.Path]] = None,
        reward_model: "Optional[RewardModel]" = None,
        modify: Optional[dict] = None,
        tune: Optional[dict] = None,
    ):
        self.task_name = task_name
        # Default secure state mutations applied on every native reset() (and
        # exposed live via the modify() pass-through). Engine path only.
        self._modify = dict(modify) if modify else None
        # Difficulty / generation knob overrides applied at reset() (vision,
        # spawn rates, room density, ...). None = vanilla NetHack generation.
        # Generation knobs must be set BEFORE the level is built, so these are
        # passed to EngineEnv.reset(tune=...), not applied after. Engine path only.
        self._tune = dict(tune) if tune else None
        # Reward is computed from the observation stream by a swappable model
        # (the fork engine has no gym reward). Defaults to score + dlvl*50 +
        # xp_level*50; pass reward_model=... to change the signal. Lazy import
        # avoids the rewards->observations->env import cycle.
        if reward_model is None:
            from .rewards import DEFAULT_REWARD_MODEL
            reward_model = DEFAULT_REWARD_MODEL()
        self._reward_model = reward_model
        # `misc` is declared in NLE's space but not always returned by MiniHack
        # tasks, which makes the passive obs-space-keys checker complain. We
        # don't read misc anywhere so it's safe to omit by default.
        self._observation_keys = observation_keys or (
            "tty_chars", "tty_colors", "tty_cursor",
            "glyphs", "chars", "colors",
            "message", "inv_strs", "inv_letters", "inv_glyphs",
            "blstats",
        )
        # `level_blob`: future blob-load path. If set, reset() loads it after the
        # engine resets. Native tasks pass None; non-None only on the engine path.
        self._level_blob = level_blob

        # Most recent observation, stored so the harness can read it back without
        # reaching into the backend. Set in reset()/step(); exposed as the
        # ``last_observation`` property (a sequence ordered by observation_keys,
        # so ``last_observation[observation_keys.index("chars")]`` works).
        self._last_observation: Optional[CoreObservation] = None

        # Harness-owned per-episode scratch: the autoexplore frontier blacklist
        # for the current level. The curriculum's _update_frontier_blacklist
        # writes it here each turn and in-skill pickers read it back; it lives on
        # the env purely as a side-channel (skills don't get the verifiers state
        # dict). Native attribute -- no backend reach-through required.
        self._frontier_blacklist_current: set = set()

        # Lazily-built keystroke->action-index map for the gym/MiniHack backend
        # (the native engine consumes keystrokes directly and needs no map).
        self._keystroke_index_map: Optional[dict] = None
        self._action_set_len: int = 0

        # All tasks are now driven by the fork engine via EngineEnv. The former
        # MiniHack/des_file gym backend (which needed nle + minihack) has been
        # retired; only native tasks (NetHackScore / NetHackChallenge) and
        # saved-level blobs remain. Branch kept as a dead guard so a stray
        # "MiniHack" task name fails loudly instead of silently mis-routing.
        self._is_native = "MiniHack" not in task_name

        if self._is_native:
            # Deferred import: engine_env imports this module, so importing it at
            # module scope would create a cycle.
            from .engine_env import EngineEnv

            self._engine: Optional["EngineEnv"] = EngineEnv()
            self._env = None
        else:
            self._engine = None
            self._env = None
            raise RuntimeError(
                "MiniHack tasks removed; use native tasks or load_level blobs. "
                f"Got task_name={task_name!r}."
            )

        # Sentinel: we require seed() before each reset() to enforce determinism.
        self._pending_seeds: Optional[tuple[int, int]] = None
        self._current_seeds: Optional[tuple[int, int]] = None

    # ----- gymnasium API -----

    def seed(self, core: int, disp: Optional[int] = None) -> tuple[int, int]:
        """
        Stage seeds for the next reset(). Both core and disp are seeded.
        reseed is ALWAYS False -- this is the whole point of the wrapper.
        """
        if disp is None:
            disp = core  # deterministic disp from core if not supplied
        # NLE exposes set_initial_seeds at the underlying nethack object.
        # We delegate at reset time because the gym env recreates state then.
        self._pending_seeds = (int(core), int(disp))
        return self._pending_seeds

    def reset(
        self,
        *,
        seeds: Optional[tuple[int, int]] = None,
        character: Optional[str] = None,
    ) -> tuple[CoreObservation, EpisodeMetadata]:
        """
        Reset the env. seeds must be set via seed() OR passed in directly.
        We refuse to reset without explicit seeds in order to make
        nondeterminism impossible to introduce by accident.
        """
        if seeds is not None:
            self._pending_seeds = seeds
        if self._pending_seeds is None:
            raise RuntimeError(
                "NetHackCoreEnv.reset() requires seeds. Call .seed(core, disp) "
                "first or pass seeds= explicitly. This is intentional: it makes "
                "trajectories reproducible by construction."
            )

        if self._is_native:
            # Engine path: EngineEnv owns seed injection + game start and returns
            # our canonical (CoreObservation, EpisodeMetadata). It applies the
            # same reseed=False discipline internally. The engine hardcodes the
            # character in its options string, so character override is not yet
            # wired (mirrors the nle path's warning below).
            if character is not None:
                logger.warning(
                    "Character override not yet wired up on the engine; got %s",
                    character,
                )
            obs, meta = self._engine.reset(seeds=self._pending_seeds, tune=self._tune)
            # Stamp the task name onto the metadata (EngineEnv labels it "engine").
            meta = EpisodeMetadata(
                seeds=meta.seeds,
                seed_hash=meta.seed_hash,
                task_name=self.task_name,
                character=character,
                extra=meta.extra,
            )
            if self._level_blob is not None:
                obs = self._engine.load_level(self._level_blob)
            if self._modify:
                obs = self._engine.modify(**self._modify)
            self._reward_model.reset(obs)
            self._current_seeds = self._pending_seeds
            self._pending_seeds = None
            self._last_observation = obs
            self._frontier_blacklist_current = set()
            logger.info("Episode start: task=%s seeds=%s hash=%s",
                        self.task_name, self._current_seeds, meta.seed_hash)
            return obs, meta

        # Non-native (MiniHack/gym) backend removed; __init__ refuses to
        # construct one, so this path is unreachable.
        raise RuntimeError(
            "MiniHack tasks removed; use native tasks or load_level blobs."
        )

    def step(self, action: int) -> tuple[CoreObservation, float, bool, bool, dict]:
        if self._is_native:
            # Engine path: EngineEnv.step returns (obs, done, info). Map to the
            # gym 5-tuple so callers don't break. The fork engine has no gym
            # reward, so reward comes from the swappable RewardModel computed over
            # the observation stream (default: score + dlvl*50 + xp_level*50).
            obs, done, info = self._engine.step(action)
            reward = self._reward_model.step(obs)
            # EngineEnv exposes no truncation signal; episodes terminate, not
            # truncate. Surface truncated=False unless info ever provides one.
            truncated = bool(info.get("truncated", False))
            self._last_observation = obs
            return obs, reward, bool(done), truncated, info
        # Non-native (MiniHack/gym) backend removed; unreachable.
        raise RuntimeError(
            "MiniHack tasks removed; use native tasks or load_level blobs."
        )

    def modify(self, **changes) -> CoreObservation:
        """Apply whitelisted, bounds-checked state mutations (native path only).

        Pass-through to :meth:`EngineEnv.modify`: validates a fixed field
        whitelist with bounds (and an optional ``goto_depth`` dungeon jump),
        rejecting unknown fields or out-of-range values before any engine write.
        Updates ``last_observation`` and returns the refreshed CoreObservation.

        Raises RuntimeError on the MiniHack/gym backend, which has no engine.
        """
        if not self._is_native:
            raise RuntimeError(
                "modify() is only available on the native engine path "
                "(not the MiniHack/gym backend)."
            )
        obs = self._engine.modify(**changes)
        self._last_observation = obs
        return obs

    def close(self) -> None:
        if self._is_native:
            self._engine.close()
        else:
            self._env.close()

    # ----- properties -----

    @property
    def action_space(self):
        if self._is_native:
            # The engine consumes raw keystroke bytes (e.g. ord(".")), so the
            # action space is the full byte range. Only PufferLib/gym consumers
            # need this; import gym lazily so the native path stays gym-free
            # unless action_space is actually requested.
            import gymnasium as gym
            return gym.spaces.Discrete(256)
        return self._env.action_space

    @property
    def current_seeds(self) -> Optional[tuple[int, int]]:
        return self._current_seeds

    @property
    def observation_keys(self) -> tuple[str, ...]:
        """The ordered observation-field names (mirrors the old nle attribute)."""
        return self._observation_keys

    @property
    def last_observation(self):
        """Most recent observation as a sequence ordered by ``observation_keys``.

        Returns a list whose ``i``-th element is the array for
        ``observation_keys[i]`` -- so existing harness code that does
        ``last_observation[observation_keys.index("chars")]`` keeps working
        without touching the backend. Returns ``None`` before the first reset.
        """
        obs = self._last_observation
        if obs is None:
            return None
        return [getattr(obs, name, None) for name in self._observation_keys]

    @property
    def frontier_blacklist_current(self) -> set:
        """Harness-owned per-level autoexplore frontier blacklist (mutable)."""
        return self._frontier_blacklist_current

    @frontier_blacklist_current.setter
    def frontier_blacklist_current(self, value) -> None:
        self._frontier_blacklist_current = set(value) if value else set()

    @property
    def underlying(self):
        """Escape hatch for code that needs the raw backend.

        Native tasks return the EngineEnv (and ``.engine`` reaches RawEngine);
        the MiniHack/des_file path returns the nle gym env. The harness no longer
        reaches through here for actions/observations: it drives the engine with
        keystroke bytes directly (the semantic action enums ARE keystrokes) and
        reads observations via the ``last_observation`` / ``observation_keys``
        properties on this class.
        """
        return self._engine if self._is_native else self._env


def _hash_seeds(core: int, disp: int) -> str:
    return hashlib.sha256(f"{core}:{disp}".encode()).hexdigest()[:12]
