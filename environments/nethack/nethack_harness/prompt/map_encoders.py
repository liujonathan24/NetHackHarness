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
    d = {
        "player": list(model.player) if model.player else None,
        "entities": [_entity_dict(e, detail) for e in model.entities],
    }
    if detail == "full":
        d["grid"] = model.grid
    return d


def json_encode(model: Any, *, detail: str = "full") -> str:
    return json.dumps(_model_dict(model, detail), separators=(",", ":"))


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
    for e in model.entities:
        parts = [e.kind, f"{e.x},{e.y}", e.description]
        if detail == "full":
            for f in _RICH_FIELDS:
                v = getattr(e, f, None)
                if v is not None:
                    parts.append(f"{f}={v}")
        lines.append(" ".join(str(p) for p in parts))
    if detail == "full":
        lines.append(f"grid: {model.grid}")
    return "\n".join(lines)
