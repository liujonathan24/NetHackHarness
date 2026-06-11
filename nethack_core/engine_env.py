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
from typing import Optional

from ._engine import RawEngine
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


def _hash_seeds(core: int, disp: int) -> str:
    return hashlib.sha256(f"{core}:{disp}".encode()).hexdigest()[:12]
