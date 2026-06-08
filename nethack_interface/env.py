"""Thin typed wrapper over NetHackCoreEnv. Typed actions execute via the existing
skill dispatch (behavioral parity with the harness); RawAction via env.step(int)."""
from __future__ import annotations

from nethack_interface.observation import Observation
from nethack_interface.actions import Action, RawAction


class NetHackInterface:
    def __init__(self, core_env, character=None):
        self._env = core_env
        self._character = character or {}
        self._raw = None
        self._structured = None

    def _shape(self) -> Observation:
        from nethack_core.observations import shape as shape_observation

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
        if isinstance(action, RawAction):
            self._raw, reward, term, trunc, info = self._env.step(action.index)
            return self._shape(), float(reward), bool(term or trunc), info
        if isinstance(action, Action):
            from nethack_harness.tools.skills import registry
            from nethack_harness.helpers import _to_action_indices

            res = registry.call(action.name, self._env, self._structured, **action.args)
            total = 0.0
            term = trunc = False
            info = {"feedback": res.feedback}
            # Skills return NLE enum/keypress values; normalize them to indices
            # into the task's action set (behavioral parity with the harness's
            # env_response, which calls _to_action_indices before stepping).
            for idx in _to_action_indices(self._env, res.actions):
                self._raw, r, term, trunc, info2 = self._env.step(idx)
                total += float(r)
                if term or trunc:
                    break
            return self._shape(), total, bool(term or trunc), info
        raise TypeError(f"unknown action: {action!r}")
