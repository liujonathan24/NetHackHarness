# environments/nethack/nethack_harness/prompt/map_encoders.py
"""Serialize the canonical MapModel as JSON or TOON, at a selectable detail.

`full`  -> rich entity attributes + the RLE grid.
`minimal` -> entity kind/coord/description only; no grid, no rich attrs.
Both project the SAME model, so JSON and TOON cannot diverge.
"""
from __future__ import annotations

import json
from typing import Any

_RICH_FIELDS = ("species", "is_pet", "obj_class", "detail")


def _entity_dict(e: Any, detail: str) -> dict:
    d = {"kind": e.kind, "x": e.x, "y": e.y, "desc": e.description}
    if detail == "full":
        for f in _RICH_FIELDS:
            v = getattr(e, f, None)
            if v is not None:
                d[f] = v
    return d


def _model_dict(model: Any, detail: str) -> dict:
    # The JSON map is the UNCOMPRESSED ascii map (rows[y][x]) plus the player
    # position — the agent reads it and perceives terrain, monsters and stairs
    # itself. We deliberately do NOT emit a pre-located feature/entity list
    # ("stair at x,y"): handing the agent where things are does its navigation
    # for it. To identify a specific cell, the agent uses nh.map.what_is(x, y).
    return {
        "player": list(model.player) if model.player else None,
        "map": list(getattr(model, "rows", []) or []),
    }


def json_encode(model: Any, *, detail: str = "full") -> str:
    return json.dumps(_model_dict(model, detail), indent=1)


def toon_encode(model: Any, *, detail: str = "full") -> str:
    """Token-frugal line-oriented encoding of the same model.

    Format (deterministic):
        @ x,y
        <kind> x,y desc[ k=v ...]
        ...
        grid: <rle>            # full detail only
    """
    lines = []
    if model.player:
        lines.append(f"@ {model.player[0]},{model.player[1]}")
    # Uncompressed ascii map (same principle as json_encode: the agent reads the
    # map; we don't hand it a located feature list).
    for row in (getattr(model, "rows", []) or []):
        lines.append(row)
    return "\n".join(lines)
