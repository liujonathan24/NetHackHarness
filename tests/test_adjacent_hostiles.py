"""Adjacency extraction + visible-glyphs summary. These let the agent skip
parsing the full map for "what's around me" and "are there monsters here"."""
from __future__ import annotations

import numpy as np

from nethack_core import (
    extract_adjacent,
    extract_hostiles_in_sight,
    extract_under_player,
)


def _tty_from(rows: list[str]) -> np.ndarray:
    """Build a 24x80 tty from row strings, padded with spaces."""
    arr = np.full((24, 80), 32, dtype=np.uint8)
    for y, line in enumerate(rows[:24]):
        for x, ch in enumerate(line[:80]):
            arr[y, x] = ord(ch)
    return arr


# ---------- adjacency ----------

def test_adjacent_basic_walls_and_floor():
    """Player surrounded by floor on E/W, hyphen walls N/S."""
    rows = ["", "---", ".@.", "---"]
    arr = _tty_from(rows)
    adj = extract_adjacent(arr)
    assert adj["W"] == "."
    assert adj["E"] == "."
    assert adj["N"] == "-"
    assert adj["S"] == "-"


def test_adjacent_no_player_returns_empty():
    """No @ in the tty → nothing to compute."""
    arr = _tty_from(["", "----", "....", "----"])
    assert extract_adjacent(arr) == {}


def test_adjacent_emits_all_eight_directions():
    rows = ["", "---", ".@d", "kj#"]  # player at (1,2); 8 neighbors all in-bounds
    arr = _tty_from(rows)
    adj = extract_adjacent(arr)
    assert set(adj.keys()) == {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}


# ---------- hostiles-in-sight ----------

def test_hostiles_dedup_and_count():
    """Two 'd' (dogs/jackals) + one 'k' → ['d (×2)', 'k']."""
    rows = ["", "  d   d  ", "  @   k  "]
    arr = _tty_from(rows)
    out = extract_hostiles_in_sight(arr)
    assert "d (×2)" in out
    assert "k" in out
    # Player should NOT appear.
    assert not any(s.startswith("@") for s in out)


def test_hostiles_ignores_terrain():
    """Walls and floor tiles should not show up as 'hostiles'."""
    rows = ["", "----", "|@.|", "----"]
    arr = _tty_from(rows)
    out = extract_hostiles_in_sight(arr)
    assert out == []


def test_hostiles_handles_no_letters():
    rows = ["", "...", ".@.", "..."]
    arr = _tty_from(rows)
    assert extract_hostiles_in_sight(arr) == []


def test_hostiles_sorted():
    rows = ["", " k d @ a "]
    arr = _tty_from(rows)
    out = extract_hostiles_in_sight(arr)
    # alphabetical
    assert out == ["a", "d", "k"]


# ---------- under_player ----------

def _chars_with(tty_player_pos, terrain_char):
    """Build a 21x79 chars grid: floor everywhere except under the @, which
    gets `terrain_char`. tty_player_pos = (x, y) in TTY coords; chars row
    is y-1 (tty has a 1-row status header above the chars area)."""
    arr = np.full((21, 79), ord("."), dtype=np.uint8)
    x, y = tty_player_pos
    if 1 <= y <= 21 and 0 <= x < 79:
        arr[y - 1, x] = ord(terrain_char)
    return arr


def test_under_player_stairs_down_from_message():
    """NLE prints 'There is a staircase down here.' when @ steps on >."""
    out = extract_under_player(None, None, "There is a staircase down here.")
    assert out is not None and "DOWN" in out and ">" in out


def test_under_player_stairs_up_from_message():
    out = extract_under_player(None, None, "There is a staircase up here.")
    assert out is not None and "UP" in out and "<" in out


def test_under_player_altar_from_message():
    out = extract_under_player(None, None, "There is an altar to a chaotic god here.")
    assert out is not None and "altar" in out


def test_under_player_fountain_from_message():
    out = extract_under_player(None, None, "There is a fountain here.")
    assert out is not None and "fountain" in out


def test_under_player_you_see_items():
    out = extract_under_player(None, None, "You see here 9 darts.")
    assert out is not None and "9 darts" in out


def test_under_player_no_message():
    """When the message buffer doesn't mention a tile, return None."""
    assert extract_under_player(None, None, "") is None
    assert extract_under_player(None, None, "The kobold misses.") is None
