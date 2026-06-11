"""Reward models — turn the observation stream into a scalar per-step reward.

The env and engine are reward-agnostic: a ``RewardModel`` maps observations to a
scalar, holding whatever state it needs. The base class stores the previous
observation, so delta / potential-shaping subclasses come for free. Swap the
model to change the reward signal without touching the env or the engine.

    env = NetHackCoreEnv(task_name="NetHackScore-v0")          # default model
    env = NetHackCoreEnv(..., reward_model=DeltaReward())       # shaped reward

Reward reads straight from ``CoreObservation.blstats`` (indices in
``observations.BLSTATS_IDX``); no dependency on the old gym reward.
"""
from __future__ import annotations

from .observations import BLSTATS_IDX

_SCORE = BLSTATS_IDX["score"]             # 9  — NetHack game score
_DEPTH = BLSTATS_IDX["depth"]             # 12 — dungeon level (dlvl)
_XPLVL = BLSTATS_IDX["experience_level"]  # 18 — experience level


class RewardModel:
    """Map the observation stream to a per-step scalar reward.

    Stateful. ``reset(obs)`` seeds the previous observation at episode start;
    ``step(obs)`` returns the reward for arriving at ``obs`` and advances the
    stored previous observation. Subclasses override ``_reward(obs, prev)``;
    ``prev`` is ``None`` on the first ``step`` after a ``reset``.
    """

    def __init__(self) -> None:
        self._prev = None

    def reset(self, obs) -> None:
        self._prev = obs

    def step(self, obs) -> float:
        reward = self._reward(obs, self._prev)
        self._prev = obs
        return float(reward)

    def _reward(self, obs, prev) -> float:  # pragma: no cover - abstract
        raise NotImplementedError


class ScoreDepthXPReward(RewardModel):
    """Simple progress reward: ``score + depth*50 + experience_level*50``.

    Reads the three quantities straight from ``blstats``. This is the default
    model — a plain progress potential. For a per-step shaped signal, wrap it in
    :class:`DeltaReward`.
    """

    DEPTH_WEIGHT = 50.0
    XP_WEIGHT = 50.0

    def potential(self, obs) -> float:
        b = obs.blstats
        return (
            float(b[_SCORE])
            + float(b[_DEPTH]) * self.DEPTH_WEIGHT
            + float(b[_XPLVL]) * self.XP_WEIGHT
        )

    def _reward(self, obs, prev) -> float:
        return self.potential(obs)


class DeltaReward(RewardModel):
    """Per-step delta of a potential model (reward shaping).

    ``reward_t = potential(obs_t) - potential(obs_{t-1})``; ``0.0`` on the first
    step. Defaults to wrapping :class:`ScoreDepthXPReward`.
    """

    def __init__(self, potential: "ScoreDepthXPReward | None" = None) -> None:
        super().__init__()
        self._model = potential or ScoreDepthXPReward()

    def _reward(self, obs, prev) -> float:
        if prev is None:
            return 0.0
        return self._model.potential(obs) - self._model.potential(prev)


# The default model used by NetHackCoreEnv when none is supplied.
DEFAULT_REWARD_MODEL = ScoreDepthXPReward
