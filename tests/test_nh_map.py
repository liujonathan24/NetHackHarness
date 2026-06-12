# tests/test_nh_map.py
from __future__ import annotations

import numpy as np

from nethack_core.map_model import MapModel, Entity
from nethack_harness.tools.code_mode import MapView


def _model():
    return MapModel(
        player=(10, 5),
        entities=[
            Entity("monster", 20, 12, 5, "wolf", species="wolf", is_pet=False),
            Entity("stair", 0, 47, 6, "stairs DOWN", detail="stairs DOWN"),
        ],
        grid="g",
    )


def test_player_and_entities():
    mv = MapView(_model())
    assert mv.player == (10, 5)
    assert len(mv.entities) == 2


def test_at_returns_entity():
    mv = MapView(_model())
    e = mv.at(12, 5)
    assert e is not None and e.kind == "monster"
    assert mv.at(0, 0) is None


def test_kind_accessors():
    mv = MapView(_model())
    assert [e.kind for e in mv.monsters] == ["monster"]
    assert [e.kind for e in mv.stairs] == ["stair"]


def test_read_only_entities_copy():
    # nh.map.entities returns a copy; mutating it must not affect the map.
    mv = MapView(_model())
    ents = mv.entities
    ents.clear()
    assert len(mv.entities) == 2
