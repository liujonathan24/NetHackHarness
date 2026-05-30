"""
Wave-2 Track B unit tests: tightened frontier predicate + visited memory.

Covers:
  (a) Seen stone (walled-in space) is NOT a frontier neighbor.
  (b) A blacklisted frontier is excluded from nearest_frontier.
  (c) The blacklist clears when max_dlvl_reached changes.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest


# Make the package importable without `prime env install`.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ENV_ROOT = os.path.dirname(_HERE)
if _ENV_ROOT not in sys.path:
    sys.path.insert(0, _ENV_ROOT)


# ---------- helpers ----------

def _grid_from_ascii(lines: list[str]) -> np.ndarray:
    """Build a chars grid from an ASCII map. Pad rows to common width."""
    w = max(len(r) for r in lines)
    out = np.full((len(lines), w), ord(" "), dtype=np.uint8)
    for y, row in enumerate(lines):
        for x, ch in enumerate(row):
            out[y, x] = ord(ch)
    return out


# ---------- (a) seen-stone vs truly-unseen ----------

def test_seen_stone_is_not_a_frontier_neighbor():
    """A walled-in corner space (3 wall neighbors, no further void) must NOT
    flag the adjacent floor as a frontier under the strict predicate."""
    from nethack_core.pathfinding import find_frontiers, is_truly_unseen

    # Floor cell with the only unknown neighbor being a single space wedged
    # between three walls — that space is "seen stone", not unexplored.
    #   |-|
    #   |.|     <-- the floor `.` at (1, 1) is fully enclosed (no real
    #   |-|         frontier).  The space at (2,1) is OUTSIDE the wall but
    #               trapped between the right wall + edge — seen stone.
    grid = _grid_from_ascii([
        "|-| ",
        "|.| ",
        "|-| ",
    ])
    # In this minimal grid the space at row 0 col 3 etc. is truly unseen
    # (it has space neighbors). To produce a *seen-stone* case put a tile
    # surrounded by walls + edge.
    enclosed_grid = _grid_from_ascii([
        "----",
        "|.. ",  # floor row; the trailing space at (3,1) is bordered by
        "----",  # walls on top, bottom, and edge on right -> seen stone.
    ])
    # The space (3, 1) has neighbors: (2,1) floor, (3,0) wall, (3,2) wall,
    # plus out-of-bounds on the right (counts as wall_or_edge). That's
    # 3 wall_or_edge + 0 space neighbors -> NOT truly unseen.
    assert is_truly_unseen(enclosed_grid, 3, 1) is False

    # Under strict mode, no floor cell in this grid should be a frontier
    # (the only space tile is seen stone).
    fr_strict = find_frontiers(enclosed_grid, strict=True)
    assert fr_strict == [], f"strict frontiers should be empty, got {fr_strict}"

    # Sanity: legacy (loose) mode WOULD have flagged the floor at (2, 1).
    fr_loose = find_frontiers(enclosed_grid, strict=False)
    assert (2, 1) in fr_loose, "legacy predicate must still flag the false frontier"


def test_truly_unseen_void_is_a_frontier_neighbor():
    """A space tile with another space neighbor (open void) must remain a
    frontier under strict mode."""
    from nethack_core.pathfinding import find_frontiers, is_truly_unseen

    # Room opens to the east into uncharted void.
    grid = _grid_from_ascii([
        "----    ",
        "|...    ",  # the floor at (3, 1) borders three spaces to the east
        "----    ",
    ])
    assert is_truly_unseen(grid, 4, 1) is True
    fr = find_frontiers(grid, strict=True)
    assert (3, 1) in fr


# ---------- (b) blacklist excludes frontier ----------

def test_blacklist_excludes_frontier_from_nearest():
    from nethack_core.pathfinding import nearest_frontier

    # Corridor with two frontiers: one near, one far. Blacklist the near one
    # and confirm nearest_frontier picks the far one (or None if unreachable).
    #   012345678
    # 0 #########
    # 1 #.......#
    # 2 #########  player at (2, 1); space east of (7,1) is the frontier
    # Two-floor corridor opening into a wide void to the east. The void
    # column at x=8 is truly unseen (its east neighbor x=9 is also space).
    grid = _grid_from_ascii([
        "--------          ",
        "|......           ",
        "--------          ",
    ])
    start = (1, 1)
    # First, with no blacklist, nearest_frontier returns the closest floor
    # tile adjacent to a truly-unseen space.
    res_open = nearest_frontier(grid, start)
    assert res_open is not None
    near_target, _ = res_open
    # Now blacklist that tile and confirm we get a different (or no) target.
    res_bl = nearest_frontier(grid, start, blacklist={near_target})
    if res_bl is not None:
        bl_target, _ = res_bl
        assert bl_target != near_target
    # Either way the blacklisted tile must not be returned.
    assert res_bl is None or res_bl[0] != near_target


# ---------- (c) blacklist clears on level change ----------

def test_blacklist_clears_on_level_change(monkeypatch):
    """_update_frontier_blacklist wipes per-level state when max_dlvl_reached
    advances."""
    # Patch the threshold down so we can blacklist deterministically.
    import nethack as nh_mod

    monkeypatch.setattr(nh_mod, "FRONTIER_STUCK_TURNS", 1)
    monkeypatch.setattr(nh_mod, "NEEDS_HIDDEN_TURNS", 1)

    # Construct a fake raw_obs object with chars + blstats.
    class FakeObs:
        def __init__(self, chars, px, py):
            self.chars = chars
            blstats = np.zeros(26, dtype=np.int64)
            blstats[0] = px
            blstats[1] = py
            self.blstats = blstats

    # Tiny room with a frontier to the east of the player.
    grid = _grid_from_ascii([
        "------",
        "|.@.. ",  # player at (2,1), floor at (3,1) borders truly-unseen (5,1)
        "------",
    ])
    # Player is at (2, 1); the floor at (3, 1) is within radius 1.
    state = {
        "raw_obs": FakeObs(grid, px=3, py=1),
        "max_dlvl_reached": 1,
        "scout_delta": 0,
        "_frontier_approach_count": {},
        "_frontier_blacklist": {},
        "_frontier_prev_dlvl": 1,
        "_needs_hidden_passage": False,
        "_zero_scout_streak": 0,
    }
    # One zero-scout turn near the frontier -> with threshold=1, it should
    # land on the blacklist.
    nh_mod._update_frontier_blacklist(state)
    bl_lvl1 = state["_frontier_blacklist"].get(1, set())
    assert bl_lvl1, f"expected at least one blacklisted frontier on L1, got {bl_lvl1}"

    # Simulate descent: dlvl advances to 2. Blacklist for L1 must be wiped
    # and approach-count map cleared.
    state["max_dlvl_reached"] = 2
    nh_mod._update_frontier_blacklist(state)
    assert state["_frontier_blacklist"].get(1, set()) == set()
    assert state["_frontier_approach_count"] == {}
    assert state["_needs_hidden_passage"] is False
    assert state["_zero_scout_streak"] == 0


def test_deadlock_flag_sets_when_all_frontiers_blacklisted(monkeypatch):
    """When no open frontier remains AND the zero-scout streak crosses the
    threshold, the `_needs_hidden_passage` flag flips True."""
    import nethack as nh_mod

    monkeypatch.setattr(nh_mod, "FRONTIER_STUCK_TURNS", 1)
    monkeypatch.setattr(nh_mod, "NEEDS_HIDDEN_TURNS", 2)

    class FakeObs:
        def __init__(self, chars, px, py):
            self.chars = chars
            blstats = np.zeros(26, dtype=np.int64)
            blstats[0] = px
            blstats[1] = py
            self.blstats = blstats

    # Player at (3,1). Floor at (4,1) borders space at (5,1) -> (4,1) is
    # the frontier and is within chebyshev radius 1 of the player.
    grid = _grid_from_ascii([
        "------",
        "|..@. ",
        "------",
    ])
    state = {
        "raw_obs": FakeObs(grid, px=3, py=1),
        "max_dlvl_reached": 1,
        "scout_delta": 0,
        "_frontier_approach_count": {},
        "_frontier_blacklist": {},
        "_frontier_prev_dlvl": 1,
        "_needs_hidden_passage": False,
        "_zero_scout_streak": 0,
    }
    # Two zero-scout turns near the only frontier:
    #   turn 1 -> increments approach -> blacklist (threshold=1).
    #   turn 2 -> open_frontiers empty + zero_scout_streak==2 -> flag flips.
    nh_mod._update_frontier_blacklist(state)
    nh_mod._update_frontier_blacklist(state)
    assert state["_needs_hidden_passage"] is True
