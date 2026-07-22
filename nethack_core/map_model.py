"""The canonical map model: a rich, typed view of the NetHack map.

Built from the NLE glyph grid (21x79). Entities carry coordinates and per-kind
attributes derived from NLE's glyph classifiers; the grid is a compact RLE of the
terrain layer. This is the one model the JSON/TOON encoders and nh.map consume.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# NLE pet glyph range (mirrors nethack_core.observations._glyph_kind).
_PET_OFF = 381
_NUMMONS = 381


@dataclass
class Entity:
    kind: str            # monster | item | stair | door | trap | feature
    glyph_id: int
    x: int
    y: int
    description: str
    species: Optional[str] = None     # monster
    is_pet: Optional[bool] = None     # monster
    obj_class: Optional[str] = None   # item
    detail: Optional[str] = None      # stair direction / door state / trap type / feature name


@dataclass
class MapModel:
    player: Optional[tuple]           # (x, y)
    entities: list                    # list[Entity]
    grid: str                         # RLE topology string
    rows: list = field(default_factory=list)  # UNCOMPRESSED ascii map: rows[y][x]
    legend: dict = field(default_factory=dict)


def _rle_grid(glyphs) -> str:
    """Compact run-length encoding of the terrain glyph rows."""
    import numpy as np

    rows = []
    for row in np.asarray(glyphs):
        out = []
        prev = None
        count = 0
        for v in row:
            v = int(v)
            if v == prev:
                count += 1
            else:
                if prev is not None:
                    out.append(f"{prev}x{count}" if count > 1 else f"{prev}")
                prev, count = v, 1
        if prev is not None:
            out.append(f"{prev}x{count}" if count > 1 else f"{prev}")
        rows.append(",".join(out))
    return "\n".join(rows)


def build_map_model(raw_obs: Any) -> MapModel:
    import numpy as np
    from nethack_core import glyphs as N
    from nethack_core.observations import _FEATURE_GLYPHS

    glyphs = np.asarray(raw_obs.glyphs)
    tty = np.asarray(getattr(raw_obs, "tty_chars"))
    blstats = np.asarray(raw_obs.blstats)
    player = (int(blstats[0]), int(blstats[1]))

    entities: list = []
    h, w = glyphs.shape
    for gy in range(h):
        for gx in range(w):
            g = int(glyphs[gy, gx])
            if N.glyph_is_monster(g) or N.glyph_is_pet(g):
                is_pet = bool(N.GLYPH_PET_OFF <= g < N.GLYPH_PET_OFF + _NUMMONS)
                try:
                    species = N.monster_name(N.glyph_to_mon(g))
                except Exception:
                    species = None
                entities.append(Entity("monster", g, gx, gy,
                                       description=species or "monster",
                                       species=species, is_pet=is_pet))
            elif N.glyph_is_object(g):
                # Item class label via the tty char on this tile (reuses the
                # proven _FEATURE_GLYPHS map); tty row = glyph row + 1.
                ty = gy + 1
                ch = int(tty[ty, gx]) if 0 <= ty < tty.shape[0] else ord("?")
                label = _FEATURE_GLYPHS.get(ch)
                entities.append(Entity("item", g, gx, gy,
                                       description=label or "object", obj_class=label))
            elif N.glyph_is_trap(g):
                # Surface the trap LOCATION (decision-critical). The specific
                # trap type lives in the cmap layer and is left for a later
                # enhancement; the coordinate is the load-bearing signal.
                entities.append(Entity("trap", g, gx, gy, description="trap"))

    # Features (stairs/doors/altars/...) from the tty layer with coordinates.
    for ty in range(1, min(22, tty.shape[0])):
        for tx in range(tty.shape[1]):
            label = _FEATURE_GLYPHS.get(int(tty[ty, tx]))
            if not label:
                continue
            if "stairs" in label:
                kind, detail = "stair", label
            elif "door" in label:
                kind, detail = "door", label
            elif label in ("weapon", "armor", "tool", "scroll", "potion", "wand",
                           "ring", "amulet", "gem/rock", "food/corpse", "gold"):
                continue  # those are items, handled via glyphs above
            else:
                kind, detail = "feature", label
            entities.append(Entity(kind, 0, tx, ty - 1, description=label, detail=detail))

    # Uncompressed ASCII map: rows[y][x] is the tty char at map cell (x, y)
    # (glyph row y == tty row y+1). This is what the player sees, no RLE — the
    # agent reads it directly instead of a compressed/located feature list.
    rows: list = []
    for y in range(h):
        ty = y + 1
        if 0 <= ty < tty.shape[0]:
            rows.append(bytes(int(c) for c in tty[ty]).decode("ascii", "replace").rstrip())
        else:
            rows.append("")

    return MapModel(player=player, entities=entities,
                    grid=_rle_grid(glyphs), rows=rows)
