"""Thin typed wrapper over NetHackCoreEnv (raw substrate).

``reset()`` yields a typed :class:`Observation`; ``step()`` takes a
:class:`RawAction` (or a bare int) and steps the engine directly. This class has
**no** dependency on the Hub.

The typed ``Action``/skill-dispatch path lives in the Hub
(``nethack_harness.interface.TypedNetHackInterface`` subclasses this and adds an
``Action`` branch to ``step``), because it needs the Hub's skill registry.
"""
from __future__ import annotations

from nethack_interface.observation import Observation
from nethack_interface.actions import RawAction


class NetHackInterface:
    def __init__(self, core_env, character=None):
        self._env = core_env
        self._character = character or {}
        self._raw = None
        self._structured = None

    def _shape(self) -> Observation:
        from nethack_core import shape as shape_observation

        self._structured = shape_observation(self._raw, self._character)
        return Observation.from_raw(
            self._raw,
            status=self._structured.status,
            inventory=self._structured.inventory,
            character=self._structured.character,
        )

    def reset(self) -> Observation:
        out = self._env.reset()
        self._raw = out[0] if isinstance(out, tuple) else out
        return self._shape()

    def step(self, action):
        """Step a RawAction (or a bare int NLE index). Returns
        ``(Observation, reward, done, info)``."""
        idx = action.index if isinstance(action, RawAction) else action
        self._raw, reward, term, trunc, info = self._env.step(int(idx))
        return self._shape(), float(reward), bool(term or trunc), info
