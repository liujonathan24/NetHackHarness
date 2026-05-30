"""Smoke test for E2: paint '?' on truly-unseen tiles adjacent to frontiers."""
from __future__ import annotations

import numpy as np

from nethack import _paint_frontiers_on_map


def _grid(rows: list[str]) -> np.ndarray:
    h, w = len(rows), max(len(r) for r in rows)
    chars = np.full((h, w), ord(" "), dtype=np.uint8)
    for y, r in enumerate(rows):
        for x, c in enumerate(r):
            chars[y, x] = ord(c)
    return chars


def test_paints_unseen_neighbor_of_frontier():
    # Tiny room with one open east edge. Frontier = the floor tile at (5,1)
    # whose east neighbor is unseen void.
    rows = [
        "-------",
        "|....@ ",
        "|.....  ",
        "-------",
    ]
    chars = _grid(rows)
    map_view = "\n".join(rows)
    # The frontier floor tile at (5, 1) has unexplored space to its east.
    frontiers = [(5, 1)]
    out = _paint_frontiers_on_map(map_view, chars, frontiers)
    # The space at (6, 1) was truly unseen and should now be '?'.
    out_rows = out.split("\n")
    assert "?" in out_rows[1], f"expected '?' painted on row 1, got {out_rows[1]!r}"


def test_does_not_overwrite_floor_or_walls():
    rows = [
        "-----",
        "|...|",
        "-----",
    ]
    chars = _grid(rows)
    map_view = "\n".join(rows)
    # A frontier on floor (1, 1) — no truly-unseen neighbors here.
    out = _paint_frontiers_on_map(map_view, chars, [(1, 1)])
    assert out == map_view, "no paint expected when no unseen neighbors"


def test_no_frontiers_is_noop():
    rows = ["|..|", "|..|"]
    chars = _grid(rows)
    map_view = "\n".join(rows)
    assert _paint_frontiers_on_map(map_view, chars, []) == map_view
