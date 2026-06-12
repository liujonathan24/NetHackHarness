"""
Tests for pathfinding.py — A* over the glyph grid and frontier-based
autoexplore. Synthesized chars arrays only — no NLE.

Run with: uv run pytest tests/test_pathfinding.py -v
"""

from __future__ import annotations

import numpy as np
import pytest

from nethack_core import actions as nethack

from nethack_harness.navigation.pathfinding import (
    a_star,
    find_frontiers,
    is_walkable,
    is_unknown,
    nearest_frontier,
)


def _grid(rows: list[str]) -> np.ndarray:
    """Build a (h, w) uint8 char grid from ASCII rows."""
    h, w = len(rows), max(len(r) for r in rows)
    out = np.full((h, w), ord(" "), dtype=np.uint8)
    for i, r in enumerate(rows):
        for j, ch in enumerate(r):
            out[i, j] = ord(ch)
    return out


# ---------- walkability ----------

def test_is_walkable_floor_and_corridor():
    assert is_walkable(ord("."))
    assert is_walkable(ord("#"))
    assert is_walkable(ord(">"))
    assert is_walkable(ord("<"))


def test_is_walkable_blocks_walls_and_rock():
    assert not is_walkable(ord("|"))
    assert not is_walkable(ord("-"))
    assert not is_walkable(ord(" "))  # rock / unseen


def test_is_walkable_allows_items_on_floor():
    """Items lying around (gold, weapons, scrolls) are walkable."""
    for ch in "$()[*/=!?\"%":
        assert is_walkable(ord(ch)), f"expected walkable: {ch!r}"


def test_is_unknown_matches_only_space():
    assert is_unknown(ord(" "))
    assert not is_unknown(ord("."))


# ---------- A* ----------

def test_a_star_straight_corridor():
    """A trivial straight-line path of 5 tiles."""
    grid = _grid([
        "@....>",
    ])
    path = a_star(grid, start=(0, 0), goal=(5, 0))
    assert path is not None
    assert len(path) == 5
    assert all(a == int(nethack.CompassDirection.E) for a in path)


def test_a_star_uses_diagonal():
    """When diagonals are cheaper, A* takes them."""
    grid = _grid([
        "@....",
        ".....",
        "....>",
    ])
    path = a_star(grid, start=(0, 0), goal=(4, 2))
    # Chebyshev distance is 4, not 6. The path should be 4 moves.
    assert path is not None and len(path) == 4


def test_a_star_walls_block():
    """A vertical wall splits the map; no path exists."""
    grid = _grid([
        "@.|.>",
        "..|..",
    ])
    assert a_star(grid, start=(0, 0), goal=(4, 0)) is None


def test_a_star_path_avoids_walls():
    """Route around a wall when there's a gap."""
    grid = _grid([
        "@.|..",
        "...>.",
    ])
    path = a_star(grid, start=(0, 0), goal=(3, 1))
    assert path is not None
    # Shortest: SE-E-E (3 actions, exploits diagonal).
    assert len(path) == 3


def test_a_star_same_start_and_goal_returns_empty_path():
    grid = _grid(["@.."])
    assert a_star(grid, start=(0, 0), goal=(0, 0)) == []


def test_a_star_goal_not_walkable_returns_none():
    grid = _grid(["@..|"])
    assert a_star(grid, start=(0, 0), goal=(3, 0)) is None


def test_a_star_blocks_diagonal_through_doorway_corner():
    """NetHack disallows diagonal moves that cut a doorway corner."""
    grid = _grid([
        "@+",
        ".>",
    ])
    # Trying to go (0,0) -> (1,1) diagonally would clip the door at (1,0).
    # The pathfinder should route around (1,0)→(1,1) via (0,1).
    path = a_star(grid, start=(0, 0), goal=(1, 1))
    assert path is not None
    # Either S then E (2 steps) — definitely not SE (1 step).
    assert len(path) >= 2


# ---------- frontier discovery ----------

def test_find_frontiers_returns_tiles_adjacent_to_unknown():
    """A room with an unexplored region on the east side."""
    grid = _grid([
        "------",
        "|...  ",
        "|...  ",
        "------",
    ])
    frontiers = set(find_frontiers(grid))
    # The eastmost floor tiles in rows 1 and 2 are adjacent to unknown.
    assert (3, 1) in frontiers
    assert (3, 2) in frontiers
    # Tiles farther west are not.
    assert (1, 1) not in frontiers


def test_find_frontiers_empty_when_fully_explored():
    """No unknown adjacencies → no frontiers."""
    grid = _grid([
        "------",
        "|....|",
        "|....|",
        "------",
    ])
    assert find_frontiers(grid) == []


# ---------- nearest_frontier ----------

def test_nearest_frontier_returns_target_and_path():
    grid = _grid([
        "------",
        "|@..  ",
        "|...  ",
        "------",
    ])
    out = nearest_frontier(grid, start=(1, 1))
    assert out is not None
    target, path = out
    # Nearest frontier is (3, 1) directly east, 2 steps.
    assert target == (3, 1)
    assert len(path) == 2


def test_nearest_frontier_none_when_fully_explored():
    grid = _grid([
        "------",
        "|@...|",
        "|....|",
        "------",
    ])
    assert nearest_frontier(grid, start=(1, 1)) is None
