"""
nethack_core.engine_env
=======================

Engine-backed NetHack env, driven directly by the custom fork engine
(``RawEngine``) instead of the ``nle`` gym wrapper used by
:class:`nethack_core.env.NetHackCoreEnv`.

Because it talks to the fork engine, it exposes capabilities the nle path
cannot:

    * ``snapshot()`` / ``restore()`` / ``free_snapshot()`` — O(arena) in-memory
      checkpoints for replay and branching (byte-exact within a dungeon level).
    * ``tune`` (and ``get_tune``/``set_tune``) — parametric difficulty knobs.

It keeps the same deterministic seed-before-reset discipline and returns the
same :class:`CoreObservation` / :class:`EpisodeMetadata` types as
``NetHackCoreEnv`` so downstream layers are unaffected.

This is intentionally a thin, honest surface: ``step`` returns
``(observation, done, info)`` — reward is a task-layer concern and is not
computed here.
"""

from __future__ import annotations

import hashlib
import pathlib
from typing import Optional

import numpy as np

from ._engine import (
    COLNO,
    NLE_BLSTATS_SIZE,
    NLE_INVENTORY_SIZE,
    NLE_INVENTORY_STR_LENGTH,
    NLE_MESSAGE_SIZE,
    NLE_TERM_CO,
    NLE_TERM_LI,
    ROWNO,
    RawEngine,
)
from .env import CoreObservation, EpisodeMetadata


class _TuneProxy:
    """``env.tune.get()`` / ``env.tune.set(**knobs)`` view over the engine knobs."""

    def __init__(self, engine: RawEngine) -> None:
        self._engine = engine

    def get(self) -> dict:
        return self._engine.get_tune()

    def set(self, **knobs) -> "_TuneProxy":
        self._engine.set_tune(**knobs)
        return self

    def catalog(self) -> list:
        return self._engine.tune_catalog()


class EngineEnv:
    """Deterministic NetHack env over the fork engine with snapshot + tune."""

    def __init__(self) -> None:
        self._engine = RawEngine()
        self._pending_seeds: Optional[tuple[int, int]] = None
        self._current_seeds: Optional[tuple[int, int]] = None
        #: ``env.tune.get()`` / ``env.tune.set(**knobs)`` difficulty-knob view.
        self.tune = _TuneProxy(self._engine)

    # ----- lifecycle -----

    def seed(self, core: int, disp: Optional[int] = None) -> tuple[int, int]:
        """Stage seeds for the next reset() (disp defaults to core)."""
        if disp is None:
            disp = core
        self._pending_seeds = (int(core), int(disp))
        return self._pending_seeds

    def reset(
        self,
        *,
        seeds: Optional[tuple[int, int]] = None,
        tune: Optional[dict] = None,
    ) -> tuple[CoreObservation, EpisodeMetadata]:
        """Start a fresh game. Seeds must be staged via seed() or passed here.

        Refusing to reset without explicit seeds keeps trajectories
        reproducible by construction (mirrors NetHackCoreEnv).

        ``tune`` applies difficulty-knob overrides before the starting level is
        generated, so generation-time knobs (e.g. room_density) reshape the
        starting floor. This is the "regenerate with these knobs" path.
        """
        if seeds is not None:
            self._pending_seeds = seeds
        if self._pending_seeds is None:
            raise RuntimeError(
                "EngineEnv.reset() requires seeds. Call .seed(core, disp) first "
                "or pass seeds= explicitly."
            )
        core, disp = self._pending_seeds
        self._engine.start(core, disp, tune=tune)
        self._current_seeds = self._pending_seeds
        self._pending_seeds = None
        meta = EpisodeMetadata(
            seeds=self._current_seeds,
            seed_hash=_hash_seeds(*self._current_seeds),
            task_name="engine",
        )
        return self._engine.to_core_observation(), meta

    def step(self, action: int) -> tuple[CoreObservation, bool, dict]:
        """Advance one action. Returns (observation, done, info)."""
        self._engine.step(action)
        done = self._engine.done
        info = {"how_done": self._engine.how_done} if done else {}
        return self._engine.to_core_observation(), done, info

    def close(self) -> None:
        self._engine.end()

    # ----- snapshot / restore (replay & branching) -----

    def snapshot(self):
        """Capture the current game state; returns an opaque handle."""
        return self._engine.snapshot()

    def restore(self, handle) -> CoreObservation:
        """Restore to a snapshot handle.

        The returned observation still reflects the most recent step's frame;
        the restored state appears in observations after the next step()
        (see RawEngine.restore).
        """
        self._engine.restore(handle)
        return self._engine.to_core_observation()

    def free_snapshot(self, handle) -> None:
        self._engine.free_snapshot(handle)

    def branch(
        self,
        n: int,
        reseed: bool = True,
        horizon: int = 40,
        action: int = ord("s"),
    ) -> list[list[bytes]]:
        """Return ``n`` continuations from the current state.

        Takes one snapshot of the current state, then restores it ``n`` times.
        With ``reseed=True`` each branch reseeds the gameplay RNG AFTER restore
        (order matters: the snapshot captures the RNG, so reseed must follow
        restore) so random-chance events diverge across branches.  With
        ``reseed=False`` the branches replay byte-identically.

        Each branch is rolled out for ``horizon`` steps of ``action`` and
        returned as a per-step trace of the map ``chars`` (one bytes object per
        step), so callers can compare branches for divergence.

        The snapshot handle is reused across all ``n`` restores (RawEngine
        snapshots support repeated restore) and freed before returning.
        """
        handle = self.snapshot()
        try:
            results: list[list[bytes]] = []
            for i in range(n):
                self.restore(handle)
                if reseed:
                    self._engine.reseed(core=1000 + i, disp=2000 + i)
                trace: list[bytes] = []
                for _ in range(horizon):
                    obs, _done, _info = self.step(action)
                    trace.append(obs.chars.tobytes())
                results.append(trace)
            return results
        finally:
            self.free_snapshot(handle)

    # ----- portable level blob save / load -----

    def save_level(self, path) -> None:
        """Serialize the current level to a portable blob written to ``path``."""
        pathlib.Path(path).write_bytes(self._engine.save_level())

    def load_level(self, path) -> CoreObservation:
        """Load a level blob from ``path`` as the current level.

        Returns the re-rendered observation.  The underlying C load is two-phase;
        RawEngine.load_level steps once (ctrl-R) internally to redraw, so the
        observation returned here already reflects the loaded level.
        """
        self._engine.load_level(pathlib.Path(path).read_bytes())
        return self._engine.to_core_observation()

    # ----- difficulty knobs -----

    def get_tune(self) -> dict:
        return self._engine.get_tune()

    def set_tune(self, **knobs) -> "EngineEnv":
        self._engine.set_tune(**knobs)
        return self

    # ----- properties -----

    @property
    def done(self) -> bool:
        return self._engine.done

    @property
    def current_seeds(self) -> Optional[tuple[int, int]]:
        return self._current_seeds

    @property
    def engine(self) -> RawEngine:
        """Escape hatch for the raw engine (snapshot internals, obs buffers)."""
        return self._engine

    @property
    def observation_space(self):
        """A gymnasium Dict space describing the CoreObservation buffers.

        Built lazily from the engine layout constants (so it is valid before the
        first reset and does not require gymnasium at import time). Only
        gym-shaped consumers (e.g. the PufferLib adapter) need this; the engine
        itself works on raw numpy buffers.
        """
        import gymnasium as gym

        u8 = lambda shape: gym.spaces.Box(  # noqa: E731
            low=0, high=255, shape=shape, dtype=np.uint8
        )
        i16 = lambda shape: gym.spaces.Box(  # noqa: E731
            low=np.iinfo(np.int16).min, high=np.iinfo(np.int16).max,
            shape=shape, dtype=np.int16,
        )
        i64 = lambda shape: gym.spaces.Box(  # noqa: E731
            low=np.iinfo(np.int64).min, high=np.iinfo(np.int64).max,
            shape=shape, dtype=np.int64,
        )
        map_shape = (ROWNO, COLNO - 1)
        tty_shape = (NLE_TERM_LI, NLE_TERM_CO)
        return gym.spaces.Dict({
            "tty_chars": u8(tty_shape),
            "tty_colors": u8(tty_shape),
            "tty_cursor": u8((2,)),
            "glyphs": i16(map_shape),
            "chars": u8(map_shape),
            "colors": u8(map_shape),
            "message": u8((NLE_MESSAGE_SIZE,)),
            "inv_strs": u8((NLE_INVENTORY_SIZE, NLE_INVENTORY_STR_LENGTH)),
            "inv_letters": u8((NLE_INVENTORY_SIZE,)),
            "inv_glyphs": i16((NLE_INVENTORY_SIZE,)),
            "blstats": i64((NLE_BLSTATS_SIZE,)),
        })


def _hash_seeds(core: int, disp: int) -> str:
    return hashlib.sha256(f"{core}:{disp}".encode()).hexdigest()[:12]
