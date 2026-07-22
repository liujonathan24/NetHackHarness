"""
Tests for observations.py — menu extraction, inventory prompt resolution, map
view masking. All run on synthetic CoreObservations so they don't need NLE.

Run with: uv run pytest tests/test_observations.py -v
"""

from __future__ import annotations

import numpy as np

from nethack_core import (
    InventoryItem,
    MenuOption,
    extract_menu,
    extract_menu_region,
    extract_inventory_prompt,
    extract_visible_features,
    parse_inventory,
    render_map_view,
)
# Private helpers are not part of the public surface; a white-box test reaches
# into the submodule for them.
from nethack_core.observations import _infer_menu_left_col, _strip_right_menu


def test_extract_visible_features_finds_stairs_and_distinguishes_up_down():
    tty = np.full((24, 80), ord(' '), dtype=np.uint8)
    tty[5, 10] = ord('>')
    tty[3, 4] = ord('<')
    tty[8, 12] = ord('_')
    out = extract_visible_features(tty)
    assert any("stairs DOWN at (10,5)" in s for s in out)
    assert any("stairs UP at (4,3)" in s for s in out)
    assert any("altar at (12,8)" in s for s in out)


def test_extract_visible_features_caps_repeated_features():
    tty = np.full((24, 80), ord(' '), dtype=np.uint8)
    for i in range(5):
        tty[3, i * 2] = ord('$')
    out = extract_visible_features(tty)
    gold = [s for s in out if "gold" in s][0]
    assert "+2 more" in gold


def test_extract_visible_features_empty_when_no_features():
    tty = np.full((24, 80), ord('.'), dtype=np.uint8)
    out = extract_visible_features(tty)
    assert out == []


def test_extract_visible_features_detects_wall_gap_open_door():
    """A `|` sandwiched between `-` in a wall row is an open door (or gap)."""
    tty = np.full((24, 80), ord(' '), dtype=np.uint8)
    # Horizontal wall row: ----|----  with `|` at (8, 5).
    for x in range(4, 13):
        tty[5, x] = ord('-')
    tty[5, 8] = ord('|')
    out = extract_visible_features(tty)
    assert any("door (open/gap) at (8,5)" in s for s in out), out


def test_extract_visible_features_detects_dot_gap_in_horizontal_wall():
    tty = np.full((24, 80), ord(' '), dtype=np.uint8)
    for x in range(4, 13):
        tty[5, x] = ord('-')
    tty[5, 8] = ord('.')
    out = extract_visible_features(tty)
    assert any("door (open/gap) at (8,5)" in s for s in out), out


def _tty_from_rows(rows: list[str], width: int = 80, height: int = 24) -> np.ndarray:
    """Build a (height, width) uint8 array from a list of ASCII rows."""
    arr = np.full((height, width), ord(" "), dtype=np.uint8)
    for i, r in enumerate(rows[:height]):
        for j, ch in enumerate(r[:width]):
            arr[i, j] = ord(ch)
    return arr


# ---------- menu extraction ----------

def test_extract_menu_returns_none_when_no_menu_open():
    tty = _tty_from_rows(["-" * 79, "@.....", ""])
    assert extract_menu(tty) is None


def test_extract_menu_parses_simple_menu():
    """An (end)-anchored menu with three options."""
    rows = [
        "",
        "  a - blessed +1 long sword",
        "  b - uncursed leather armor",
        "  c - 3 uncursed daggers",
        "(end)",
    ]
    tty = _tty_from_rows(rows)
    menu = extract_menu(tty)
    assert menu is not None
    assert len(menu) == 3
    assert menu[0].letter == "a"
    assert menu[0].description == "blessed +1 long sword"
    assert menu[2].description == "3 uncursed daggers"


def test_extract_menu_handles_n_of_m_pagination():
    """NetHack paginates long menus as `(1 of 2)`."""
    rows = [
        "  a - item one",
        "  b - item two",
        "(1 of 2)",
    ]
    tty = _tty_from_rows(rows)
    menu = extract_menu(tty)
    assert menu is not None and len(menu) == 2


def test_extract_menu_region_reports_left_column():
    """The masking path needs the left column where menu lines begin."""
    rows = [
        "@......                    a - first option",
        ".#####                     b - second option",
        "                          (end)",
    ]
    tty = _tty_from_rows(rows)
    menu, col = extract_menu_region(tty)
    assert menu is not None and len(menu) == 2
    # 'a' is at column 27 (after "@......                    ")
    assert col == 27


# ---------- inventory prompt extraction ----------

def test_extract_inventory_prompt_resolves_letters_to_items():
    """`What do you want to throw? [abh]` → bag of items by letter."""
    inv = [
        InventoryItem(letter="a", description="a +1 long sword (weapon in hand)", glyph=0),
        InventoryItem(letter="b", description="a dagger", glyph=0),
        InventoryItem(letter="h", description="3 darts", glyph=0),
        InventoryItem(letter="z", description="a wand of fire", glyph=0),
    ]
    prompt = extract_inventory_prompt("What do you want to throw? [abh]", inv)
    assert prompt is not None
    assert prompt["action"] == "throw"
    assert [i.letter for i in prompt["items"]] == ["a", "b", "h"]


def test_extract_inventory_prompt_none_when_no_prompt():
    assert extract_inventory_prompt("You see here a pile of gold.", []) is None


# ---------- inventory parsing ----------

def test_parse_inventory_decodes_blessed_and_wielded_flags():
    """Inventory strings carry blessed/cursed and worn/wielded metadata."""
    inv_strs = np.zeros((55, 80), dtype=np.uint8)
    inv_letters = np.zeros(55, dtype=np.uint8)
    inv_glyphs = np.zeros(55, dtype=np.int16)

    descriptions = [
        (ord("a"), b"a blessed +1 long sword (weapon in hand)"),
        (ord("b"), b"a cursed -2 leather armor (being worn)"),
        (ord("c"), b"3 uncursed daggers"),
        (ord("d"), b"a wand of fire (unidentified)"),
    ]
    for i, (letter, desc) in enumerate(descriptions):
        inv_letters[i] = letter
        inv_strs[i, : len(desc)] = list(desc)

    items = parse_inventory(inv_strs, inv_letters, inv_glyphs)
    assert len(items) == 4
    assert items[0].is_blessed is True and items[0].is_wielded is True
    assert items[1].is_blessed is False and items[1].is_worn is True
    assert items[2].is_blessed is False  # uncursed
    assert items[3].is_blessed is None   # unidentified


# ---------- map view masking ----------

def test_strip_right_menu_truncates_at_left_col():
    row = "@......                    a - first option"
    assert _strip_right_menu(row, 27) == "@......                    "


def test_strip_right_menu_leaves_short_rows_alone():
    """A row shorter than the cut column should be untouched."""
    assert _strip_right_menu("@..", 27) == "@.."


def test_render_map_view_strips_menu_when_present():
    """The map view should not contain menu lines when a menu is open."""
    rows = [
        "@......                    a - first option",
        ".#####                     b - second option",
        "                          (end)",
    ]
    tty = _tty_from_rows(rows)
    menu, col = extract_menu_region(tty)
    rendered = render_map_view(tty, menu, col)
    assert "first option" not in rendered
    assert "second option" not in rendered
    assert "@......" in rendered  # the map content survives


def test_render_map_view_no_menu_passthrough():
    rows = ["@.....", "######"]
    tty = _tty_from_rows(rows)
    rendered = render_map_view(tty, menu=None)
    assert rendered.splitlines()[0] == "@....."
    assert rendered.splitlines()[1] == "######"


def test_infer_menu_left_col_fallback():
    """If we didn't compute the column up front, the fallback scans the rows."""
    rows = [
        "@......                    a - first option",
        ".#####                     b - second option",
    ]
    assert _infer_menu_left_col(rows) == 27


# ---------- y/n prompt detection (v0.0.39) ----------

def test_yn_prompt_really_attack_answers_no():
    """v0.0.49 peaceful-safety: "Really attack?" only fires on peacefuls.
    Auto-answer NO preserves pets and avoids alignment penalties."""
    from nethack_core import extract_yn_prompt
    yn = extract_yn_prompt("Really attack the little dog? [yn] (n)")
    assert yn is not None
    assert yn["answer"] == "n"
    assert yn["default"] == "n"


def test_yn_prompt_really_quit_answers_no():
    from nethack_core import extract_yn_prompt
    yn = extract_yn_prompt("Really quit? [yn] (n)")
    assert yn is not None
    assert yn["answer"] == "n"


def test_yn_prompt_unknown_falls_back_to_parenthesized_default():
    from nethack_core import extract_yn_prompt
    yn = extract_yn_prompt("Some unknown prompt? [yn] (y)")
    assert yn is not None
    assert yn["answer"] == "y"


def test_yn_prompt_no_default_falls_back_to_ESC():
    from nethack_core import extract_yn_prompt
    yn = extract_yn_prompt("Strange prompt? [yn]")
    assert yn is not None
    assert yn["answer"] == "ESC"


def test_yn_prompt_returns_none_when_no_yn_brackets():
    from nethack_core import extract_yn_prompt
    assert extract_yn_prompt("You hit the kobold.") is None
    assert extract_yn_prompt("") is None


def test_yn_prompt_pick_up_answers_yes():
    from nethack_core import extract_yn_prompt
    yn = extract_yn_prompt("Pick up the gold? [yn] (y)")
    assert yn is not None
    assert yn["answer"] == "y"


def test_yn_prompt_throw_away_answers_no():
    from nethack_core import extract_yn_prompt
    yn = extract_yn_prompt("Throw away the food ration? [yn] (n)")
    assert yn is not None
    assert yn["answer"] == "n"


def test_yn_prompt_swap_places_answers_yes():
    from nethack_core import extract_yn_prompt
    yn = extract_yn_prompt("Do you want to swap places with the dog? [yn] (y)")
    assert yn is not None
    assert yn["answer"] == "y"


def test_extract_adjacent_labels_monster_letters_with_class_hint():
    """`f` adjacent should render as `f(cat/small feline)` so the model
    doesn't hallucinate it into 'fireplace' (trace 9071d001)."""
    from nethack_core import extract_adjacent
    tty = np.full((24, 80), ord('.'), dtype=np.uint8)
    # Player @ at (10, 10); cat `f` adjacent west.
    tty[10, 10] = ord('@')
    tty[10, 9] = ord('f')
    tty[10, 11] = ord('d')
    out = extract_adjacent(tty)
    assert out.get("W", "").startswith("f("), out
    assert "cat" in out["W"]
    assert "dog" in out.get("E", "") or "canine" in out.get("E", "")


def test_extract_adjacent_marks_pet_when_glyphs_provided():
    """When a glyph ID lands in the pet range, the adjacent annotation
    must say PET so the agent doesn't attack its own kitten."""
    from nethack_core import extract_adjacent
    from nethack_core.observations import _GLYPH_PET_OFF, _GLYPH_MON_OFF
    tty = np.full((24, 80), ord('.'), dtype=np.uint8)
    tty[10, 10] = ord('@')
    tty[10, 9] = ord('f')   # pet kitten west
    tty[10, 11] = ord('d')  # hostile jackal east
    glyphs = np.zeros((21, 79), dtype=np.int16)
    # glyphs row = tty row - 1, so tty row 10 = glyph row 9.
    glyphs[9, 9] = _GLYPH_PET_OFF + 0      # any pet glyph id
    glyphs[9, 11] = _GLYPH_MON_OFF + 1     # any hostile glyph id (non-zero so it's a real monster)
    out = extract_adjacent(tty, glyphs)
    assert "PET" in out.get("W", ""), out
    assert "hostile" in out.get("E", ""), out


def test_extract_adjacent_no_glyphs_falls_back_to_class_only():
    """Backward-compatible: no glyphs arg means no pet/hostile annotation."""
    from nethack_core import extract_adjacent
    tty = np.full((24, 80), ord('.'), dtype=np.uint8)
    tty[10, 10] = ord('@')
    tty[10, 9] = ord('f')
    out = extract_adjacent(tty)
    assert "PET" not in out.get("W", "")
    assert "hostile" not in out.get("W", "")
    assert "cat" in out.get("W", "")
