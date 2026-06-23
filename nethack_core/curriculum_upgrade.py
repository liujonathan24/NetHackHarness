"""Probabilistic Valkyrie stat-upgrade model for the curriculum's deep jump.

When the curriculum jumps the hero from dungeon level 3 to ~48, the hero's
*stats only* (experience level, HP, and the six attributes) are raised to a
value sampled from a model of where real Valkyrie players are at that depth.

Two model sources, same interface:

* :meth:`ValkyrieUpgradeModel.analytic` — a hand-built table derived from
  NetHack Valkyrie progression (used so the curriculum runs end-to-end before
  the dataset is ingested).
* :meth:`ValkyrieUpgradeModel.from_artifact` — loads a JSON artifact fit from
  the NLE human dataset (NLD) Valkyrie subset (see
  ``tools/build_valkyrie_model.py``). Same shape as the analytic table.

Sampling is deterministic given the episode seed, so a curriculum episode is
reproducible.

Attribute values use NetHack's internal encoding: strength is 3..125 (19..118
== 18/01..18/00, 119..125 == 19..25); the others are plain 3..25.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from typing import Optional

# Stats the model produces (and the curriculum injects). max_hp drives hp too.
STAT_FIELDS = ("xp_level", "max_hp", "str", "dex", "con", "int", "wis", "cha")

# Inclusive clamp bounds per stat (match the engine's modify() whitelist).
_BOUNDS = {
    "xp_level": (1, 30),
    "max_hp": (1, 30000),
    "str": (3, 125),
    "dex": (3, 25),
    "con": (3, 25),
    "int": (3, 25),
    "wis": (3, 25),
    "cha": (3, 25),
}


@dataclass
class _Dist:
    """A (mean, std) per stat used to sample a value (clamped + rounded)."""

    mean: float
    std: float


# Analytic deep-Gehennom Valkyrie profile (depths 46-50), derived from typical
# NetHack female-Valkyrie progression: Str maxes intrinsically at 18/** (=118)
# early; Con is high; Int/Wis/Cha are dump stats; HP/XP scale with depth. These
# are deliberately conservative and get replaced by the NLD-fit table.
_ANALYTIC_TABLE: dict[int, dict[str, _Dist]] = {
    46: {
        "xp_level": _Dist(15, 2.0), "max_hp": _Dist(150, 30),
        "str": _Dist(118, 0.0), "dex": _Dist(16, 2.0), "con": _Dist(18, 1.0),
        "int": _Dist(9, 2.0), "wis": _Dist(13, 2.5), "cha": _Dist(8, 2.0),
    },
    47: {
        "xp_level": _Dist(16, 2.0), "max_hp": _Dist(158, 30),
        "str": _Dist(118, 0.0), "dex": _Dist(16, 2.0), "con": _Dist(18, 1.0),
        "int": _Dist(9, 2.0), "wis": _Dist(14, 2.5), "cha": _Dist(8, 2.0),
    },
    48: {
        "xp_level": _Dist(17, 2.0), "max_hp": _Dist(166, 32),
        "str": _Dist(118, 0.0), "dex": _Dist(17, 2.0), "con": _Dist(18, 1.0),
        "int": _Dist(10, 2.0), "wis": _Dist(14, 2.5), "cha": _Dist(9, 2.0),
    },
    49: {
        "xp_level": _Dist(17, 2.0), "max_hp": _Dist(172, 32),
        "str": _Dist(118, 0.0), "dex": _Dist(17, 2.0), "con": _Dist(18, 1.0),
        "int": _Dist(10, 2.0), "wis": _Dist(15, 2.5), "cha": _Dist(9, 2.0),
    },
    50: {
        "xp_level": _Dist(18, 2.0), "max_hp": _Dist(180, 34),
        "str": _Dist(118, 0.0), "dex": _Dist(17, 2.0), "con": _Dist(18, 1.0),
        "int": _Dist(10, 2.0), "wis": _Dist(15, 2.5), "cha": _Dist(9, 2.0),
    },
}


def _clamp_round(value: float, field: str) -> int:
    lo, hi = _BOUNDS[field]
    return max(lo, min(hi, int(round(value))))


class ValkyrieUpgradeModel:
    """A per-depth distribution over Valkyrie stats; samples a stat vector."""

    def __init__(self, table: dict[int, dict[str, _Dist]], source: str = "analytic"):
        if not table:
            raise ValueError("upgrade model table is empty")
        self._table = table
        self.source = source

    # ----- constructors -----

    @classmethod
    def analytic(cls) -> "ValkyrieUpgradeModel":
        return cls(_ANALYTIC_TABLE, source="analytic")

    @classmethod
    def from_artifact(cls, path) -> "ValkyrieUpgradeModel":
        """Load a JSON artifact: {"by_depth": {"48": {"max_hp": {"mean":..,
        "std":..}, ...}, ...}}. Falls back to analytic if the file is absent."""
        with open(path) as fh:
            blob = json.load(fh)
        table: dict[int, dict[str, _Dist]] = {}
        for depth_str, stats in blob["by_depth"].items():
            table[int(depth_str)] = {
                f: _Dist(float(d["mean"]), float(d.get("std", 0.0)))
                for f, d in stats.items()
            }
        return cls(table, source=str(path))

    @classmethod
    def load(cls, artifact: Optional[str] = None) -> "ValkyrieUpgradeModel":
        """from_artifact(artifact) if given and present, else analytic()."""
        if artifact:
            import os
            if os.path.exists(artifact):
                return cls.from_artifact(artifact)
        return cls.analytic()

    # ----- sampling -----

    def _nearest_depth(self, depth: int) -> int:
        return min(self._table, key=lambda d: abs(d - depth))

    def sample(self, depth: int, rng: Optional[random.Random] = None) -> dict[str, int]:
        """Sample a stat vector for ``depth``. Deterministic given ``rng``.

        Returns a dict with keys STAT_FIELDS plus ``hp`` (== sampled max_hp, so
        the upgraded hero arrives at full health).
        """
        rng = rng or random.Random(0)
        band = self._table[self._nearest_depth(depth)]
        out: dict[str, int] = {}
        for field in STAT_FIELDS:
            dist = band[field]
            value = dist.mean if dist.std <= 0 else rng.gauss(dist.mean, dist.std)
            out[field] = _clamp_round(value, field)
        out["hp"] = out["max_hp"]  # arrive at full health
        return out
