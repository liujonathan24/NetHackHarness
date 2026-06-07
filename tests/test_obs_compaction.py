"""Token-reduction tests for format_observation_as_chat.

The chat-format helper drives our per-turn token bill. These tests assert
the compaction tricks from docs/PROMPTING_SURVEY.md fire correctly without
losing information.
"""
from __future__ import annotations

from dataclasses import dataclass

from nethack import (
    _glyph_run_encode,
    _run_length_encode_messages,
    _strip_blank_rows,
    format_observation_as_chat,
)


@dataclass
class _Obs:
    map_view: str
    status: dict
    character: dict
    inventory: list
    messages: list
    menu: object = None
    inventory_prompt: object = None
    adjacent: dict = None  # type: ignore  # populated in __post_init__

    def __post_init__(self):
        if self.adjacent is None:
            self.adjacent = {}


@dataclass
class _Item:
    letter: str
    description: str


def _basic_obs(map_view="@..", inventory=None):
    return _Obs(
        map_view=map_view,
        status={"hitpoints": 10, "max_hitpoints": 10, "armor_class": 9, "depth": 1, "time": 0, "experience_level": 1, "gold": 0},
        character={"role": "monk", "race": "human", "alignment": "neutral"},
        inventory=inventory or [],
        messages=[],
    )


# ---------- glyph-run encoding ----------

def test_glyph_run_encodes_long_floor_runs():
    out = _glyph_run_encode("." * 20)
    assert out == ".{20}"


def test_glyph_run_leaves_short_runs_alone():
    """Default min_run=5; runs of 4 are not encoded."""
    assert _glyph_run_encode("....") == "...."


def test_glyph_run_handles_corridors():
    out = _glyph_run_encode("#" * 10 + "@" + "." * 10)
    assert "#{10}" in out
    assert ".{10}" in out


def test_glyph_run_per_row():
    """Encoding runs each row independently; non-floor/corridor chars pass through."""
    rows = "..........\n@@@@@\n....\n##########"  # 4-dot row stays
    out = _glyph_run_encode(rows)
    assert out == ".{10}\n@@@@@\n....\n#{10}"


# ---------- blank-row stripping ----------

def test_strip_blank_rows_drops_empty_rows():
    out = _strip_blank_rows("a\n\n\nb\n   \nc")
    assert out == "a\nb\nc"


def test_strip_blank_rows_trims_trailing_whitespace():
    out = _strip_blank_rows("abc   \ndef")
    assert out == "abc\ndef"


# ---------- end-to-end compaction in format_observation_as_chat ----------

def test_format_compact_is_smaller_than_raw():
    """A wide tty with lots of blanks and corridors should compact significantly."""
    huge_map = "\n".join([
        "  " + "." * 70,
        "  " + "#" * 70,
        "                                                      ",  # blank-ish
        "  " + "@" + "." * 70,
        "  " + "." * 70,
        "",
        "",
    ])
    obs = _basic_obs(map_view=huge_map)
    raw = format_observation_as_chat(obs, journal=None, compact=False)
    compact = format_observation_as_chat(obs, journal=None, compact=True)
    assert len(compact) < len(raw), f"compact={len(compact)} not smaller than raw={len(raw)}"
    # Sanity: the player marker (@) must survive both renderings.
    assert "@" in raw and "@" in compact


def test_journal_diff_only_unchanged_on_repeat():
    """Journal block emits '(unchanged since last turn)' when keys+objective haven't changed."""
    from nethack_harness.memory.journal import Journal
    j = Journal()
    j.pin_objective("explore")
    j.add_note("strategy", "head east")
    obs = _basic_obs()
    state: dict = {}
    first = format_observation_as_chat(obs, journal=j, state=state)
    second = format_observation_as_chat(obs, journal=j, state=state)
    assert "strategy" in first
    # Notes diffed out, but the pinned objective always re-renders so the
    # agent retains its goal post-compaction. Bug fixed 2026-05-16.
    assert "notes unchanged" in second or "unchanged since last turn" in second
    assert "strategy" not in second
    assert "Objective: explore" in second


def test_journal_diff_refires_on_new_note():
    """Adding a note must invalidate the journal-diff cache."""
    from nethack_harness.memory.journal import Journal
    j = Journal()
    j.pin_objective("explore")
    j.add_note("a", "x")
    obs = _basic_obs()
    state: dict = {}
    format_observation_as_chat(obs, journal=j, state=state)
    j.add_note("b", "y")
    second = format_observation_as_chat(obs, journal=j, state=state)
    assert "(unchanged" not in second
    assert "b: y" in second


def test_inventory_diff_only_unchanged_on_repeat():
    """Calling twice with the same inventory + state should mark second one as unchanged."""
    inv = [_Item(letter="a", description="dagger"), _Item(letter="b", description="potion")]
    obs = _basic_obs(inventory=inv)
    state: dict = {}
    first = format_observation_as_chat(obs, journal=None, state=state)
    second = format_observation_as_chat(obs, journal=None, state=state)
    assert "dagger" in first  # full listing first time
    assert "INVENTORY (unchanged)" in second
    assert "dagger" not in second  # not re-emitted


def test_inventory_diff_refires_when_changed():
    inv1 = [_Item(letter="a", description="dagger")]
    inv2 = [_Item(letter="a", description="dagger"), _Item(letter="b", description="potion")]
    state: dict = {}
    format_observation_as_chat(_basic_obs(inventory=inv1), journal=None, state=state)
    second = format_observation_as_chat(_basic_obs(inventory=inv2), journal=None, state=state)
    assert "potion" in second
    assert "(unchanged)" not in second


def test_compact_off_disables_token_savers():
    """compact=False produces the raw v0.0.15-era output (no glyph runs, no diff)."""
    obs = _basic_obs(map_view="." * 30)
    out = format_observation_as_chat(obs, journal=None, compact=False)
    assert ".{30}" not in out  # raw map
    assert "." * 30 in out


def test_message_run_length_collapses_combat_spam():
    msgs = ["You hit the kobold.", "You hit the kobold.", "You hit the kobold.", "The kobold misses."]
    out = _run_length_encode_messages(msgs)
    assert out == ["You hit the kobold. (x3)", "The kobold misses."]


def test_message_run_length_passthrough_when_no_repeats():
    msgs = ["a", "b", "c"]
    assert _run_length_encode_messages(msgs) == msgs


def test_message_run_length_handles_empty():
    assert _run_length_encode_messages([]) == []


def test_compact_preserves_status_and_messages():
    """Compaction must not drop functional info — status/messages still present."""
    obs = _basic_obs()
    obs.messages = ["You hit the kobold.", "The kobold misses."]
    out = format_observation_as_chat(obs, journal=None, compact=True)
    assert "HP: 10/10" in out
    assert "You hit the kobold" in out
    assert "kobold misses" in out


def test_status_line_includes_player_position_when_available():
    """move_to(x,y) is useless without knowing the agent's current (x,y).
    Trace 9071d001 showed model picking essentially random move_to targets;
    surfacing 'Pos: (x,y)' in STATUS lets it compute relative paths."""
    obs = _basic_obs()
    obs.status = dict(obs.status)
    obs.status.update({"x": 42, "y": 11})
    out = format_observation_as_chat(obs, journal=None, compact=True)
    assert "Pos: (42,11)" in out
