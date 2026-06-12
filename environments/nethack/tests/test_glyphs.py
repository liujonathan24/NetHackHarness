"""Tests for the pure-Python glyph classification (nethack_core.glyphs).

These assert the predicates are internally consistent with the fork's glyph
numbering (offset chain derived from third_party/NetHack/src/include/display.h)
and exercise both the scalar and vectorized (numpy-array) call paths the
harness uses. The one-time parity check against nle.nethack over the full glyph
range lived in a scratch test run before nle was uninstalled; it matched
exactly (all predicates, glyph_to_mon, the cmap LUT, and all 381 monster names).
"""
import numpy as np

from nethack_core import glyphs as G


def test_offset_chain_matches_fork_headers():
    # Values from display.h's GLYPH_*_OFF macros with NUMMONS=381,
    # NUM_OBJECTS=453, MAXPCHARS=96.
    assert G.NUMMONS == 381
    assert G.NUM_OBJECTS == 453
    assert G.MAXPCHARS == 96
    assert G.GLYPH_MON_OFF == 0
    assert G.GLYPH_PET_OFF == 381
    assert G.GLYPH_CMAP_OFF == 2359
    assert G.GLYPH_STATUE_OFF == 5595
    assert G.MAX_GLYPH == 5976


def test_scalar_predicates_partition_ranges():
    # A monster glyph is a monster, not an object/cmap/trap.
    g = G.GLYPH_MON_OFF + 5
    assert G.glyph_is_monster(g) is True
    assert G.glyph_is_object(g) is False
    assert G.glyph_is_cmap(g) is False

    # Pet range.
    p = G.GLYPH_PET_OFF + 3
    assert G.glyph_is_pet(p) is True
    assert G.glyph_is_monster(p) is True  # pet counts as a monster

    # Object range.
    o = G.GLYPH_OBJ_OFF + 10
    assert G.glyph_is_object(o) is True
    assert G.glyph_is_monster(o) is False

    # Cmap + trap sub-range.
    assert G.glyph_is_cmap(G.GLYPH_CMAP_OFF) is True
    trap = G.GLYPH_CMAP_OFF + 42  # S_arrow_trap
    assert G.glyph_is_trap(trap) is True
    assert G.glyph_is_cmap(trap) is True
    assert G.glyph_is_trap(G.GLYPH_CMAP_OFF) is False  # cmap 0 isn't a trap


def test_vectorized_predicates_return_bool_arrays():
    arr = np.arange(G.MAX_GLYPH, dtype=np.int64)
    for pred in (G.glyph_is_monster, G.glyph_is_pet, G.glyph_is_object,
                 G.glyph_is_trap, G.glyph_is_cmap):
        out = pred(arr)
        assert isinstance(out, np.ndarray)
        assert out.dtype == bool
        assert out.shape == arr.shape

    # Exact true-counts (each class occupies a contiguous range).
    assert int(G.glyph_is_monster(arr).sum()) == 4 * G.NUMMONS
    assert int(G.glyph_is_pet(arr).sum()) == G.NUMMONS
    assert int(G.glyph_is_object(arr).sum()) == G.NUM_OBJECTS + 2 * G.NUMMONS
    assert int(G.glyph_is_cmap(arr).sum()) == G.MAXPCHARS
    assert int(G.glyph_is_trap(arr).sum()) == G.TRAPNUM


def test_scalar_and_vector_agree():
    arr = np.arange(G.MAX_GLYPH, dtype=np.int64)
    for pred in (G.glyph_is_monster, G.glyph_is_pet, G.glyph_is_object,
                 G.glyph_is_trap, G.glyph_is_cmap):
        vec = np.asarray(pred(arr), bool)
        scal = np.array([bool(pred(int(i))) for i in range(G.MAX_GLYPH)])
        assert np.array_equal(vec, scal), pred.__name__


def test_glyph_to_mon_and_names():
    # Monster glyph 0 -> giant ant; pet of the same species maps identically.
    assert G.glyph_to_mon(G.GLYPH_MON_OFF) == 0
    assert G.glyph_to_mon(G.GLYPH_PET_OFF) == 0
    assert G.monster_name(0) == "giant ant"
    assert G.monster_name(G.NUMMONS - 1) == "apprentice"
    assert G.monster_name(G.NUMMONS) is None  # out of range
    assert len(G.MONSTER_NAMES) == G.NUMMONS


def test_cmap_clean_char_lut():
    lut = G.cmap_clean_char_lut()
    assert lut.shape == (G.MAXPCHARS,)
    assert lut[0] == ord(" ")            # dark/unexplored
    assert lut[24] == ord(">")           # staircase down
    assert lut[23] == ord("<")           # staircase up
    assert lut[19] == ord(".")           # floor of a room
    # Closed doors are blocked for pathing.
    assert G.CMAP_CLOSED_DOOR_INDICES == frozenset({15, 16})
    for i in G.CMAP_CLOSED_DOOR_INDICES:
        assert lut[i] == ord("|")
