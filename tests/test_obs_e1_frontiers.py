"""Smoke tests for Wave-3 Track C variant E1 — surface frontiers + progress
signal to the model.

We construct a fake game state with a hand-rolled `chars` grid (so we don't
have to spin up NLE) and assert the four new obs blocks render correctly:

  1. === FRONTIERS === (top-5 nearest, with bearing + tile kind)
  2. Coverage indicator inside the EXPLORATION block
  3. Per-turn scout-delta line ("revealed N new tiles" / "retreading")
  4. === SPATIAL BELIEF === replacing the legacy descent-salience block

Plus a fallback test for "(no frontiers — try `search` ...)".
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from nethack import (
    _e1_bearing,
    _e1_exploration_block,
    _e1_frontiers_block,
    _e1_spatial_belief_block,
    format_observation_as_chat,
)


# ---------- fakes ----------


@dataclass
class _RawObs:
    chars: np.ndarray
    blstats: np.ndarray


@dataclass
class _Obs:
    map_view: str
    status: dict
    character: dict
    inventory: list
    messages: list
    menu: object = None
    inventory_prompt: object = None
    adjacent: dict = field(default_factory=dict)


def _make_chars_with_room(px: int = 5, py: int = 5) -> np.ndarray:
    """21x79 uint8 grid. Small visible room around (px, py); the rest is
    'space' (unknown). The room walkable interior abuts unknowns on the
    east / south edge so we get clean frontiers there."""
    chars = np.full((21, 79), ord(" "), dtype=np.uint8)
    # 9x5 visible region: floor inside, walls around.
    for y in range(py - 2, py + 3):
        for x in range(px - 4, px + 5):
            if y in (py - 2, py + 2):
                chars[y, x] = ord("-")
            elif x in (px - 4, px + 4):
                chars[y, x] = ord("|")
            else:
                chars[y, x] = ord(".")
    # Carve a corridor east leading into unknown space; the east end of the
    # corridor will be the closest frontier.
    for x in range(px + 5, px + 9):
        chars[py, x] = ord("#")
    return chars


def _basic_state(px: int = 5, py: int = 5, scout_delta: int | None = 4) -> dict:
    chars = _make_chars_with_room(px, py)
    blstats = np.zeros(27, dtype=np.int64)
    blstats[0] = px
    blstats[1] = py
    state: dict = {
        "raw_obs": _RawObs(chars=chars, blstats=blstats),
        "_e1_obs": True,
        "_seen_stairs_down": set(),
        "max_dlvl_reached": 1,
        "scout_tiles_seen": {(1, x, y) for y in range(py - 1, py + 2) for x in range(px - 3, px + 4)},
    }
    if scout_delta is not None:
        state["scout_delta"] = scout_delta
    return state


def _basic_structured(px: int = 5, py: int = 5):
    return _Obs(
        map_view="@..",
        status={"hitpoints": 10, "max_hitpoints": 10, "armor_class": 9,
                "depth": 1, "time": 0, "experience_level": 1, "gold": 0,
                "x": px, "y": py},
        character={"role": "monk", "race": "human", "alignment": "neutral"},
        inventory=[],
        messages=[],
    )


# ---------- bearings ----------


def test_bearing_cardinal():
    assert _e1_bearing(0, -3) == "N"
    assert _e1_bearing(0, 3) == "S"
    assert _e1_bearing(3, 0) == "E"
    assert _e1_bearing(-3, 0) == "W"


def test_bearing_diagonal():
    assert _e1_bearing(3, -3) == "NE"
    assert _e1_bearing(-3, 3) == "SW"


def test_bearing_zero():
    assert _e1_bearing(0, 0) == "@"


# ---------- FRONTIERS block ----------


def test_frontiers_block_renders_top_5():
    state = _basic_state()
    out = _e1_frontiers_block(state)
    text = "\n".join(out)
    assert "=== FRONTIERS ===" in text
    # We expect at least one frontier on the east corridor end.
    assert "corridor" in text or "room edge" in text
    # Cap of 5 + header + trailing blank line.
    assert len(out) <= 7


def test_frontiers_block_fallback_when_none():
    """A fully-walled 1-tile world has no frontiers."""
    chars = np.full((21, 79), ord("|"), dtype=np.uint8)
    chars[5, 5] = ord(".")
    blstats = np.zeros(27, dtype=np.int64)
    blstats[0], blstats[1] = 5, 5
    state = {"raw_obs": _RawObs(chars=chars, blstats=blstats), "_e1_obs": True}
    out = _e1_frontiers_block(state)
    assert any("no frontiers" in line and "search" in line for line in out)


def test_frontiers_lines_contain_bearing_and_distance():
    state = _basic_state(px=5, py=5)
    out = _e1_frontiers_block(state)
    # Find at least one frontier line of the form "(x, y)  ~D steps DIR  — kind"
    frontier_lines = [ln for ln in out if ln.startswith("(") and "steps" in ln]
    assert frontier_lines, f"no frontier lines in {out}"
    sample = frontier_lines[0]
    assert "~" in sample and "steps" in sample and "—" in sample


# ---------- EXPLORATION block ----------


def test_exploration_block_includes_coverage_and_delta():
    state = _basic_state(scout_delta=4)
    out = _e1_exploration_block(state, _basic_structured())
    text = "\n".join(out)
    assert "=== EXPLORATION ===" in text
    assert "Explored:" in text and "tiles" in text
    assert "frontiers open" in text
    assert "revealed 4 new tiles" in text


def test_exploration_block_retreading_on_zero_delta():
    state = _basic_state(scout_delta=0)
    out = _e1_exploration_block(state, _basic_structured())
    assert any("retreading" in line for line in out)


def test_exploration_block_turn0_when_delta_missing():
    state = _basic_state(scout_delta=None)
    out = _e1_exploration_block(state, _basic_structured())
    assert any("turn 0" in line for line in out)


# ---------- SPATIAL BELIEF block ----------


def test_spatial_belief_emits_bearings_and_no_stairs():
    state = _basic_state()
    out = _e1_spatial_belief_block(state, _basic_structured())
    text = "\n".join(out)
    assert "=== SPATIAL BELIEF ===" in text
    assert "Unexplored bearings:" in text
    assert "Known stairs DOWN: none yet" in text


def test_spatial_belief_surfaces_known_stairs():
    state = _basic_state()
    state["_seen_stairs_down"].add((38, 11))
    out = _e1_spatial_belief_block(state, _basic_structured())
    assert any("(38,11)" in line for line in out)


# ---------- end-to-end through format_observation_as_chat ----------


def test_e1_blocks_appear_in_full_formatter():
    state = _basic_state(scout_delta=2)
    obs = _basic_structured()
    rendered = format_observation_as_chat(obs, journal=None, state=state, compact=True)
    assert "=== FRONTIERS ===" in rendered
    assert "=== EXPLORATION ===" in rendered
    assert "=== SPATIAL BELIEF ===" in rendered
    assert "revealed 2 new tiles" in rendered


def test_non_e1_variants_unchanged():
    """When _e1_obs is False (e.g. variants B1/N/ND), the new blocks must
    not appear — prior eval comparisons stay valid."""
    state = _basic_state(scout_delta=2)
    state["_e1_obs"] = False
    obs = _basic_structured()
    rendered = format_observation_as_chat(obs, journal=None, state=state, compact=True)
    assert "=== FRONTIERS ===" not in rendered
    assert "=== EXPLORATION ===" not in rendered
    assert "=== SPATIAL BELIEF ===" not in rendered


def test_e1_token_budget_under_100():
    """E1's four new blocks together should stay under ~100 tokens at one
    output per turn. We use a 4-char heuristic for token count."""
    state = _basic_state(scout_delta=2)
    blocks = (
        _e1_frontiers_block(state)
        + _e1_exploration_block(state, _basic_structured())
        + _e1_spatial_belief_block(state, _basic_structured())
    )
    block_text = "\n".join(blocks)
    approx_tokens = len(block_text) / 4
    assert approx_tokens < 100, f"E1 blocks ~{approx_tokens:.0f} tokens, expected <100\n{block_text}"
