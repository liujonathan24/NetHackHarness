"""Shared pytest fixtures for the prompt/rendering tests.

`make_structured_obs` builds a minimal real `StructuredObservation` (the actual
dataclass from `nethack_core.observations`, not a duck-typed stand-in) populated
with status, inventory, map_view, under_player, and adjacent — the attributes the
include_map / include_local gates of `format_observation_as_chat` key off of.
"""
from __future__ import annotations

import pytest

from nethack_core import InventoryItem, StructuredObservation


@pytest.fixture
def make_core_env():
    """Factory for a real `NetHackCoreEnv` (NetHackScore-v0), mirroring how the
    existing tests (e.g. tests/test_skills.py) construct one. The env refuses to
    reset without explicit seeds (reproducibility by construction), so the
    factory seeds it before handing it back. Returns a callable so each test
    gets a fresh, seeded env instance."""
    from nethack_core import NetHackCoreEnv

    def _make():
        env = NetHackCoreEnv(task_name="NetHackScore-v0")
        env.seed(core=42, disp=42)
        return env

    return _make


@pytest.fixture
def make_structured_obs():
    def _make() -> StructuredObservation:
        return StructuredObservation(
            map_view="@..\n...",
            messages=[],
            inventory=[
                InventoryItem(letter="a", description="a +1 dagger", glyph=0),
            ],
            status={
                "hitpoints": 10,
                "max_hitpoints": 10,
                "armor_class": 9,
                "depth": 1,
                "time": 0,
                "experience_level": 1,
                "gold": 0,
            },
            character={"role": "monk", "race": "human", "alignment": "neutral"},
            adjacent={"N": ".", "E": ".", "S": ".", "W": "."},
            under_player="stairs DOWN",
        )

    return _make
