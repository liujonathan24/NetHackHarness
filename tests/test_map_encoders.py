# tests/test_map_encoders.py
from __future__ import annotations

import json

from nethack_core.map_model import MapModel, Entity
from nethack_harness.prompt.map_encoders import json_encode, toon_encode


def _model():
    return MapModel(
        player=(10, 5),
        entities=[
            Entity("monster", 20, 12, 5, "wolf", species="wolf", is_pet=False),
            Entity("stair", 0, 47, 6, "stairs DOWN", detail="stairs DOWN"),
        ],
        grid="2353x79",
    )


def test_json_full_has_entities_and_grid():
    s = json_encode(_model(), detail="full")
    d = json.loads(s)
    assert d["player"] == [10, 5]
    kinds = {e["kind"] for e in d["entities"]}
    assert {"monster", "stair"} <= kinds
    assert "grid" in d
    # rich attrs present at full detail
    mon = next(e for e in d["entities"] if e["kind"] == "monster")
    assert mon["species"] == "wolf"


def test_json_minimal_trims_attrs_and_grid():
    full = json_encode(_model(), detail="full")
    mini = json_encode(_model(), detail="minimal")
    assert "grid" not in json.loads(mini)
    mon = next(e for e in json.loads(mini)["entities"] if e["kind"] == "monster")
    assert "species" not in mon  # rich attrs dropped
    assert len(mini) < len(full)


def test_toon_deterministic_and_smaller_than_json():
    m = _model()
    a = toon_encode(m, detail="full")
    b = toon_encode(m, detail="full")
    assert a == b  # deterministic
    assert len(a) < len(json_encode(m, detail="full"))  # more compact
