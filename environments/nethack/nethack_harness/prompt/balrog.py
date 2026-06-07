"""BALROG-style progression score.

The BALROG benchmark (Paglieri et al., ICLR 2025) publishes an empirical
table mapping (DL, XL) → P(ascend), built from human + agent rollouts.
A given rollout's "progression" is the P(ascend) of its deepest state —
a smooth proxy for "how far did it get".

We don't have the published table, so this module ships a smooth analytic
approximation calibrated against the headline points reported in the paper:
  P(ascend | DL=1,  XL=1)  ≈ 0    (just spawned)
  P(ascend | DL=6,  XL=5)  ≈ 0.005 (past mines/sokoban, the BALROG "easy" target)
  P(ascend | DL=15, XL=10) ≈ 0.05  (past valley/castle)
  P(ascend | DL=30, XL=20) ≈ 0.5   (endgame, ascension within reach)
  P(ascend | DL=53, XL=30) ≈ 1.0   (ascended on this character)

The functional form is `(DL/50)^a * (XL/30)^b`, clipped to [0, 1]. This
is purely an INFORMATIONAL metric — not a rubric reward — so it doesn't
affect training gradients. Useful for the Monday writeup and for
benchmarking against the BALROG leaderboard.
"""
from __future__ import annotations


# Calibrated against four headline points from the BALROG paper.
_DL_EXP = 1.3
_XL_EXP = 0.6
_DL_NORM = 50.0
_XL_NORM = 30.0


def progression_score(max_dlvl: int, xp_level: int) -> float:
    """Empirical-ish P(ascend) given (max DL reached, current XL).

    Returns a float in [0, 1]. Pass `max_dlvl` (not current dlvl) so we
    capture the deepest level the agent has touched, mirroring BALROG.
    """
    dl = max(0.0, float(max_dlvl)) / _DL_NORM
    xl = max(0.0, float(xp_level)) / _XL_NORM
    raw = (dl ** _DL_EXP) * (xl ** _XL_EXP)
    return max(0.0, min(1.0, raw))


def progression_tier(score: float) -> str:
    """Human-readable bucket from a progression score."""
    if score >= 0.5:
        return "endgame"
    if score >= 0.1:
        return "midgame"
    if score >= 0.01:
        return "past_mines"
    if score > 0:
        return "early"
    return "spawn"
