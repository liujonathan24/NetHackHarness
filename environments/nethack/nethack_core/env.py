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

import gymnasium as gym
import nle  # noqa: F401  -- registers NetHack-* envs with gym
import numpy as np

try:
    import minihack  # noqa: F401  -- registers MiniHack-* envs (optional)
except ImportError:
    pass  # MiniHack tiers will fail at make-time; that's fine.

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
    ):
        self.task_name = task_name
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

        # NATIVE tasks (NetHackScore / NetHackChallenge) are driven by the fork
        # engine via EngineEnv; the MiniHack/des_file path still uses nle's gym
        # env until the curriculum migration (Phase E) retires it. Branch on the
        # task name: anything mentioning "MiniHack" stays on the gym backend.
        self._is_native = "MiniHack" not in task_name

        if self._is_native:
            # Deferred import: engine_env imports this module, so importing it at
            # module scope would create a cycle.
            from .engine_env import EngineEnv

            self._engine: Optional["EngineEnv"] = EngineEnv()
            self._env = None
        else:
            self._engine = None
            # NB: passing observation_keys here is what filters NLE's huge default
            # obs dict. no_progress_timeout is only accepted by NetHackChallenge;
            # des_file is required by MiniHack-Skill-Custom-v0; not by NLE tasks.
            make_kwargs: dict[str, Any] = {
                "observation_keys": self._observation_keys,
                "max_episode_steps": max_episode_steps,
            }
            if "Challenge" in task_name:
                make_kwargs["no_progress_timeout"] = no_progress_timeout
            if "MiniHack" in task_name and des_file is not None:
                make_kwargs["des_file"] = des_file
            try:
                self._env = gym.make(task_name, **make_kwargs)
            except gym.error.NameNotFound as e:
                if "MiniHack" in task_name:
                    raise RuntimeError(
                        f"Tier requires MiniHack but it is not installed. "
                        f"Install with: pip install nethack[minihack] "
                        f"(adds the samvelyan/minihack git dep and its system build deps "
                        f"cmake/bison/flex/libbz2-dev). Original error: {e}"
                    ) from e
                raise

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
            obs, meta = self._engine.reset(seeds=self._pending_seeds)
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
            self._current_seeds = self._pending_seeds
            self._pending_seeds = None
            logger.info("Episode start: task=%s seeds=%s hash=%s",
                        self.task_name, self._current_seeds, meta.seed_hash)
            return obs, meta

        # Optionally set character. NLE supports a NETHACKOPTIONS env var
        # but the cleaner path is its `character` kwarg on construction.
        # TODO(jonathan): expose `character` on construction or via gym.make wrapper.
        if character is not None:
            logger.warning("Character override not yet wired up; got %s", character)

        core, disp = self._pending_seeds
        # The actual seed injection: NLE's env exposes `nethack.set_initial_seeds`
        # which takes (core, disp, reseed). We force reseed=False.
        self._env.unwrapped.nethack.set_initial_seeds(core, disp, False)
        obs, _info = self._env.reset()

        self._current_seeds = self._pending_seeds
        self._pending_seeds = None

        meta = EpisodeMetadata(
            seeds=self._current_seeds,
            seed_hash=_hash_seeds(*self._current_seeds),
            task_name=self.task_name,
            character=character,
        )
        logger.info("Episode start: task=%s seeds=%s hash=%s",
                    self.task_name, self._current_seeds, meta.seed_hash)
        return CoreObservation.from_nle(obs), meta

    def step(self, action: int) -> tuple[CoreObservation, float, bool, bool, dict]:
        if self._is_native:
            # Engine path: EngineEnv.step returns (obs, done, info). Map to the
            # gym 5-tuple so callers don't break. Reward is 0.0 by design — the
            # gym reward was never consumed as a learning signal: the verifiers
            # rubric (scout/descent/success/ascension) derives reward entirely
            # from observation-derived `state` fields, and the only readers of
            # NetHackCoreEnv.step's reward (nethack.py's total_reward) feed it to
            # debug telemetry (helpers.py JSONL "reward") and a write-only
            # state["last_reward"]. The fork engine has no gym-score reward; the
            # milestone/curriculum layer owns reward.
            obs, done, info = self._engine.step(action)
            # EngineEnv exposes no truncation signal; episodes terminate, not
            # truncate. Surface truncated=False unless info ever provides one.
            truncated = bool(info.get("truncated", False))
            return obs, 0.0, bool(done), truncated, info
        obs, reward, terminated, truncated, info = self._env.step(action)
        return CoreObservation.from_nle(obs), float(reward), bool(terminated), bool(truncated), info

    def close(self) -> None:
        if self._is_native:
            self._engine.close()
        else:
            self._env.close()

    # ----- properties -----

    @property
    def action_space(self) -> gym.Space:
        if self._is_native:
            # The engine consumes raw keystroke bytes (e.g. ord(".")), so the
            # action space is the full byte range. gym consumers (puffer adapter)
            # only need a Discrete; this is the minimal correct shape.
            return gym.spaces.Discrete(256)
        return self._env.action_space

    @property
    def current_seeds(self) -> Optional[tuple[int, int]]:
        return self._current_seeds

    @property
    def underlying(self):
        """Escape hatch for code that needs the raw backend.

        Native tasks return the EngineEnv (and ``.engine`` reaches RawEngine);
        the MiniHack/des_file path returns the nle gym env. NOTE: the harness
        layer (nethack_harness skills/curriculum) still reaches for nle-only
        attributes via ``underlying.unwrapped.actions`` etc.; that layer is
        migrated to the engine in Phase E and is not exercised by native-engine
        callers yet.
        """
        return self._engine if self._is_native else self._env


def _hash_seeds(core: int, disp: int) -> str:
    return hashlib.sha256(f"{core}:{disp}".encode()).hexdigest()[:12]
