# tests/test_map_model.py
from __future__ import annotations

import numpy as np
import nle.nethack as N

from nethack_core.map_model import build_map_model, MapModel, Entity


def _obs_with(glyphs, tty_chars=None, x=40, y=10):
    class O: pass
    o = O()
    o.glyphs = glyphs
    o.tty_chars = tty_chars if tty_chars is not None else np.full((24, 80), ord(" "), np.uint8)
    blstats = np.zeros((27,), np.int64); blstats[0] = x; blstats[1] = y
    o.blstats = blstats
    return o


def test_player_position():
    g = np.full((21, 79), N.GLYPH_CMAP_OFF, np.int32)  # all floor-ish
    m = build_map_model(_obs_with(g, x=12, y=5))
    assert isinstance(m, MapModel)
    assert m.player == (12, 5)


def test_monster_entity_has_species_and_pet_flag():
    g = np.full((21, 79), N.GLYPH_CMAP_OFF, np.int32)
    # place a wild monster glyph and a pet glyph
    wild = N.GLYPH_MON_OFF + 20            # some monster
    pet = N.GLYPH_PET_OFF + 20             # same species, tame
    g[5, 10] = wild
    g[6, 11] = pet
    m = build_map_model(_obs_with(g))
    mons = [e for e in m.entities if e.kind == "monster"]
    by_xy = {(e.x, e.y): e for e in mons}
    assert (10, 5) in by_xy and (11, 6) in by_xy
    assert by_xy[(10, 5)].species == N.permonst(N.glyph_to_mon(wild)).mname
    assert by_xy[(10, 5)].is_pet is False
    assert by_xy[(11, 6)].is_pet is True


def test_item_entity_has_class():
    g = np.full((21, 79), N.GLYPH_CMAP_OFF, np.int32)
    g[3, 4] = N.GLYPH_OBJ_OFF + 20
    tty = np.full((24, 80), ord(" "), np.uint8)
    tty[4, 4] = ord("(")  # tty row = glyph row + 1; resolves item-class label
    m = build_map_model(_obs_with(g, tty_chars=tty))
    items = [e for e in m.entities if e.kind == "item"]
    assert items and items[0].obj_class is not None


def test_grid_is_rle_string():
    g = np.full((21, 79), N.GLYPH_CMAP_OFF, np.int32)
    m = build_map_model(_obs_with(g))
    assert isinstance(m.grid, str) and len(m.grid) > 0
