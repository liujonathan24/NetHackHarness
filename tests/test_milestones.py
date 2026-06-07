"""
Tests for milestones.py. All run on synthesized observations — no NLE rollouts.

We build a tiny fake observation type with `tty_chars`, `message`, and
`blstats` attributes; that's everything the milestone checks read.

Run with: uv run pytest tests/test_milestones.py -v
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from nethack_harness.curriculum.milestones import (
    DUNGEON_MAIN,
    DUNGEON_MINES,
    DUNGEON_SOKOBAN,
    any_of,
    all_of,
    castle_reached_milestone,
    get_milestone,
    list_milestones,
    mine_town_milestone,
    oracle_consult_milestone,
    quest_complete_milestone,
    reach_dlvl_milestone,
    sokoban_complete_milestone,
)


@dataclass
class _FakeObs:
    tty_chars: np.ndarray
    message: np.ndarray
    blstats: np.ndarray


def _make_obs(*, dungeon: int = 0, dlvl: int = 1, screen_text: str = "", message_text: str = "") -> _FakeObs:
    """Build a synthesized obs with the given branch / dlvl / screen text."""
    tty = np.full((24, 80), ord(" "), dtype=np.uint8)
    for i, row in enumerate(screen_text.split("\n")[:24]):
        for j, ch in enumerate(row[:80]):
            tty[i, j] = ord(ch)

    msg = np.zeros(256, dtype=np.uint8)
    for i, ch in enumerate(message_text[:256]):
        msg[i] = ord(ch)

    blstats = np.zeros(26, dtype=np.int64)
    blstats[12] = dlvl
    blstats[23] = dungeon
    blstats[24] = dlvl
    return _FakeObs(tty_chars=tty, message=msg, blstats=blstats)


# ---------- mine_town ----------

def test_mine_town_fires_on_mines_branch_with_marker():
    obs = _make_obs(dungeon=DUNGEON_MINES, dlvl=5, screen_text="Welcome to Mine Town")
    state: dict = {}
    assert mine_town_milestone.check(obs, state) is True
    assert state["milestone_mine_town"] is True


def test_mine_town_does_not_fire_in_main_dungeon():
    """Even if the message says 'Mine Town', not being in the Mines branch
    means it's a hallucination or other branch reference; don't fire."""
    obs = _make_obs(dungeon=DUNGEON_MAIN, dlvl=2, screen_text="Mine Town signpost reference")
    assert mine_town_milestone.check(obs, {}) is False


def test_mine_town_is_idempotent():
    """Once fired, stays fired across subsequent observations."""
    obs_fires = _make_obs(dungeon=DUNGEON_MINES, screen_text="Mine Town")
    state: dict = {}
    mine_town_milestone.check(obs_fires, state)
    # Later we're somewhere unrelated — still True.
    obs_unrelated = _make_obs(dungeon=DUNGEON_MAIN, screen_text="")
    assert mine_town_milestone.check(obs_unrelated, state) is True


# ---------- sokoban_complete ----------

def test_sokoban_complete_fires_on_hero_message():
    obs = _make_obs(dungeon=DUNGEON_SOKOBAN, screen_text="You feel like a Sokoban hero!")
    assert sokoban_complete_milestone.check(obs, {}) is True


def test_sokoban_complete_fires_on_cheating_message():
    """The negative-path completion message still counts as 'puzzle solved'."""
    obs = _make_obs(dungeon=DUNGEON_SOKOBAN, screen_text="You feel guilty for cheating.")
    assert sokoban_complete_milestone.check(obs, {}) is True


def test_sokoban_complete_does_not_fire_on_irrelevant_text():
    obs = _make_obs(dungeon=DUNGEON_SOKOBAN, screen_text="There is a boulder here.")
    assert sokoban_complete_milestone.check(obs, {}) is False


# ---------- oracle_consult ----------

def test_oracle_consult_fires_on_major_consultation_marker():
    obs = _make_obs(screen_text="The Oracle proclaims: 'It is time to go home.'")
    assert oracle_consult_milestone.check(obs, {}) is True


def test_oracle_consult_does_not_fire_on_sight_alone():
    """Seeing the Oracle level is not the same as consulting."""
    obs = _make_obs(screen_text="The Oracle is here.")
    assert oracle_consult_milestone.check(obs, {}) is False


# ---------- reach_dlvl ----------

def test_reach_dlvl_fires_on_exact_target():
    m = reach_dlvl_milestone(3)
    assert m.check(_make_obs(dungeon=DUNGEON_MAIN, dlvl=3), {}) is True


def test_reach_dlvl_fires_on_deeper():
    m = reach_dlvl_milestone(3)
    assert m.check(_make_obs(dungeon=DUNGEON_MAIN, dlvl=5), {}) is True


def test_reach_dlvl_does_not_fire_above_target():
    m = reach_dlvl_milestone(3)
    assert m.check(_make_obs(dungeon=DUNGEON_MAIN, dlvl=2), {}) is False


def test_reach_dlvl_only_fires_in_main_dungeon():
    """Mines dlvl 5 is not the same as main dlvl 5."""
    m = reach_dlvl_milestone(5)
    assert m.check(_make_obs(dungeon=DUNGEON_MINES, dlvl=5), {}) is False


# ---------- composition ----------

def test_any_of_short_circuits_on_first_match():
    composite = any_of(
        reach_dlvl_milestone(5),
        sokoban_complete_milestone,
    )
    # dlvl 5 satisfies the first child.
    assert composite.check(_make_obs(dungeon=DUNGEON_MAIN, dlvl=5), {}) is True


def test_all_of_requires_every_child():
    composite = all_of(
        reach_dlvl_milestone(2),
        sokoban_complete_milestone,
    )
    state: dict = {}
    # dlvl=2 satisfies the first, but Sokoban hasn't completed.
    assert composite.check(_make_obs(dungeon=DUNGEON_MAIN, dlvl=2), state) is False
    # Now the Sokoban completion marker fires AND we're still on dlvl 2.
    obs2 = _make_obs(dungeon=DUNGEON_MAIN, dlvl=2, screen_text="You feel like a Sokoban hero!")
    assert composite.check(obs2, state) is True


# ---------- registry ----------

def test_get_milestone_returns_each_built_in():
    for name in list_milestones():
        m = get_milestone(name)
        assert m.name == name


def test_get_milestone_raises_on_unknown():
    with pytest.raises(KeyError):
        get_milestone("not_a_real_milestone")


# ---------- quest_complete ----------

def test_quest_complete_fires_on_artifact_message():
    obs = _make_obs(screen_text="You feel that the Amulet of Yendor is here.")
    state: dict = {}
    assert quest_complete_milestone.check(obs, state) is True
    assert state["milestone_quest_completed"] is True


def test_quest_complete_does_not_fire_on_unrelated_screen():
    obs = _make_obs(screen_text="The orc misses.")
    assert quest_complete_milestone.check(obs, {}) is False


def test_quest_complete_idempotent():
    state: dict = {}
    obs_fire = _make_obs(screen_text="You have completed the Quest.")
    assert quest_complete_milestone.check(obs_fire, state) is True
    obs_unrelated = _make_obs(screen_text="")
    assert quest_complete_milestone.check(obs_unrelated, state) is True  # sticky


# ---------- castle_reached ----------

def test_castle_reached_requires_deep_main_dungeon():
    """Castle marker on dlvl 5 must NOT fire — castle is dlvl 25+."""
    obs = _make_obs(dungeon=DUNGEON_MAIN, dlvl=5, screen_text="Welcome to the Castle")
    assert castle_reached_milestone.check(obs, {}) is False


def test_castle_reached_fires_on_deep_castle_marker():
    obs = _make_obs(dungeon=DUNGEON_MAIN, dlvl=26, screen_text="Welcome to the Castle")
    assert castle_reached_milestone.check(obs, {}) is True


def test_castle_reached_idempotent():
    state: dict = {}
    obs_fire = _make_obs(dungeon=DUNGEON_MAIN, dlvl=27, screen_text="Welcome to the Castle")
    assert castle_reached_milestone.check(obs_fire, state) is True
    obs_unrelated = _make_obs(dungeon=DUNGEON_MAIN, dlvl=1)
    assert castle_reached_milestone.check(obs_unrelated, state) is True


def test_list_milestones_includes_new_ones():
    names = list_milestones()
    assert "quest_complete" in names
    assert "castle_reached" in names
