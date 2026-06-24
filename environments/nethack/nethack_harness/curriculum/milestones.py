"""
nethack_harness.curriculum.milestones
=======================

Termination predicates for the Pokemon-route-style curriculum.

Where a MiniHack tier ends because we asked NLE to run for K steps and stop,
a *milestone* tier ends because the player accomplished something intrinsic
to NetHack: reaching the Mines Town shopkeepers, completing the Sokoban
puzzle chain, consulting the Oracle, etc.

Each milestone is a `Milestone` dataclass with:
  * name      — slug used in curriculum.py
  * description — for the system prompt / rubric text
  * check(obs, state) -> bool   — examined every step, fires terminal once

The detectors here are deliberately conservative: they fire on specific game
messages or unambiguous blstats transitions, not on heuristics. False
positives would end episodes early; false negatives just delay until the
fallback max_episode_steps cap. We prefer the latter.

References:
  * NetHack 3.6 source — `src/dungeon.c` for the branch structure
  * NetHack wiki — Sokoban, Gnomish Mines, Oracle of Delphi entries
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np


# blstats indices (mirrors observations.BLSTATS_IDX; duplicated to avoid
# circular import. If you change one, change both.)
_BLSTAT_DLVL = 12
_BLSTAT_DUNGEON_NUMBER = 23
_BLSTAT_LEVEL_NUMBER = 24

# NetHack dungeon branch numbers (from src/dungeon.c, stable since 3.6.0).
DUNGEON_MAIN = 0
DUNGEON_MINES = 1
DUNGEON_SOKOBAN = 2
DUNGEON_QUEST = 3
DUNGEON_LUDIOS = 4
DUNGEON_GEHENNOM = 5
DUNGEON_VLAD = 6
DUNGEON_PLANES = 7


@dataclass
class Milestone:
    """A composable termination condition."""
    name: str
    description: str
    check: Callable[[object, dict], bool]


# ---------- helpers ----------

def _decode_tty(obs) -> str:
    """Render the entire tty to a string for substring scanning."""
    return "\n".join(
        "".join(chr(c) for c in row) for row in obs.tty_chars
    )


def _decode_message(obs) -> str:
    return bytes(obs.message).split(b"\x00", 1)[0].decode("ascii", errors="replace")


def _dungeon_number(obs) -> int:
    return int(obs.blstats[_BLSTAT_DUNGEON_NUMBER])


def _level_number(obs) -> int:
    return int(obs.blstats[_BLSTAT_LEVEL_NUMBER])


# ---------- milestone: Mine Town reached ----------

_MINE_TOWN_MARKERS = (
    "Mine Town",
    "Welcome to Mine Town",
    "You enter Mine Town",
)


def _mine_town_check(obs, state: dict) -> bool:
    """
    Mine Town is on level 5–8 of the Mines branch. Easiest signal: the game
    prints 'Welcome to Mine Town' on entry. We also keep a one-shot 'seen'
    flag in state so a single match terminates even if the message scrolls.
    """
    if state.get("milestone_mine_town"):
        return True
    if _dungeon_number(obs) != DUNGEON_MINES:
        return False
    screen = _decode_tty(obs)
    for marker in _MINE_TOWN_MARKERS:
        if marker in screen:
            state["milestone_mine_town"] = True
            return True
    return False


mine_town_milestone = Milestone(
    name="mine_town",
    description="Reach Mine Town in the Gnomish Mines branch.",
    check=_mine_town_check,
)


# ---------- milestone: Sokoban completed ----------

_SOKOBAN_COMPLETION_MARKERS = (
    # Top of Sokoban: pick up the Bag of Holding or Amulet of Reflection.
    "You feel like a Sokoban hero",
    "You feel guilty for cheating",  # negative path — we still count "Sokoban done"
)


def _sokoban_completed_check(obs, state: dict) -> bool:
    if state.get("milestone_sokoban_completed"):
        return True
    screen = _decode_tty(obs)
    for marker in _SOKOBAN_COMPLETION_MARKERS:
        if marker in screen:
            state["milestone_sokoban_completed"] = True
            return True
    return False


sokoban_complete_milestone = Milestone(
    name="sokoban_complete",
    description="Complete the Sokoban puzzle branch (reach top, pick up prize).",
    check=_sokoban_completed_check,
)


# ---------- milestone: Oracle consulted ----------

# After paying the Oracle, you get a message containing one of these. The
# minor consultation costs little; the major reveals your god's relation.
_ORACLE_CONSULTATION_MARKERS = (
    "Oracle proclaims",
    "Oracle whispers",
    "the major consultation",
    "the minor consultation",
)
# Just *seeing* the Oracle level (dungeon_main, but with a specific NetHack
# special-level signature) is a weaker but useful intermediate signal.
_ORACLE_LEVEL_MARKER = "The Oracle"


def _oracle_consulted_check(obs, state: dict) -> bool:
    if state.get("milestone_oracle_consulted"):
        return True
    screen = _decode_tty(obs)
    for marker in _ORACLE_CONSULTATION_MARKERS:
        if marker in screen:
            state["milestone_oracle_consulted"] = True
            return True
    return False


oracle_consult_milestone = Milestone(
    name="oracle_consult",
    description="Find and consult the Oracle of Delphi.",
    check=_oracle_consulted_check,
)


# ---------- milestone: reached a specific dungeon level ----------

def reach_dlvl_milestone(target_dlvl: int) -> Milestone:
    """
    Convenience: reach dungeon level N in the main dungeon. Useful for
    tier definitions like 'mini_dungeon = main dungeon, end at dlvl 3'.
    """

    def check(obs, state: dict) -> bool:
        if state.get(f"milestone_dlvl_{target_dlvl}"):
            return True
        if _dungeon_number(obs) == DUNGEON_MAIN and int(obs.blstats[_BLSTAT_LEVEL_NUMBER]) >= target_dlvl:
            state[f"milestone_dlvl_{target_dlvl}"] = True
            return True
        return False

    return Milestone(
        name=f"reach_dlvl_{target_dlvl}",
        description=f"Reach dungeon level {target_dlvl} in the main dungeon.",
        check=check,
    )


def _reached_planes_check(obs, state: dict) -> bool:
    """Curriculum success: the hero is on the Elemental Planes (dnum 7)."""
    if state.get("milestone_reached_planes"):
        return True
    if _dungeon_number(obs) == DUNGEON_PLANES:
        state["milestone_reached_planes"] = True
        return True
    return False


reached_planes_milestone = Milestone(
    name="reached_planes",
    description="Reach the Elemental Planes (the curriculum's ascent target).",
    check=_reached_planes_check,
)


# ---------- milestone: completed the role quest ----------

_QUEST_COMPLETE_MARKERS = (
    "You feel that the Amulet of",   # quest reward awarded
    "You hear the rule",             # quest leader speech upon return
    "successfully completed the Quest",
    "You have completed the Quest",
)


def _quest_complete_check(obs, state: dict) -> bool:
    if state.get("milestone_quest_completed"):
        return True
    screen = _decode_tty(obs)
    for marker in _QUEST_COMPLETE_MARKERS:
        if marker in screen:
            state["milestone_quest_completed"] = True
            return True
    return False


quest_complete_milestone = Milestone(
    name="quest_complete",
    description="Complete your role's quest and obtain the quest artifact.",
    check=_quest_complete_check,
)


# ---------- milestone: reached the Castle (Valley of the Dead → Castle) ----------

_CASTLE_MARKERS = (
    "Be careful! Better hold your breath",  # appears when entering moat near castle
    "moat",                                  # broad: any moat encounter (castle is the canonical one)
    "Welcome to the Castle",
    "The walls are made of",                 # castle interior description
)


def _castle_reached_check(obs, state: dict) -> bool:
    if state.get("milestone_castle_reached"):
        return True
    screen = _decode_tty(obs)
    # Castle is in main dungeon at dlvl ~25-29. Combine signals to avoid
    # false positives from random fountain moats.
    dlvl_ok = False
    try:
        dlvl_ok = (
            _dungeon_number(obs) == DUNGEON_MAIN
            and int(obs.blstats[_BLSTAT_DLVL]) >= 25
        )
    except Exception:
        pass
    if dlvl_ok and any(m in screen for m in _CASTLE_MARKERS):
        state["milestone_castle_reached"] = True
        return True
    return False


castle_reached_milestone = Milestone(
    name="castle_reached",
    description="Reach the Castle (dlvl ~25-29) and survive the entrance moat.",
    check=_castle_reached_check,
)


# ---------- composition: any/all of N milestones ----------

def any_of(*milestones: Milestone, name: str = "any_of", description: Optional[str] = None) -> Milestone:
    """Fire when ANY of the inner milestones fires."""
    desc = description or "Any of: " + ", ".join(m.name for m in milestones)

    def check(obs, state: dict) -> bool:
        return any(m.check(obs, state) for m in milestones)

    return Milestone(name=name, description=desc, check=check)


def all_of(*milestones: Milestone, name: str = "all_of", description: Optional[str] = None) -> Milestone:
    """Fire when ALL of the inner milestones have fired at least once."""
    desc = description or "All of: " + ", ".join(m.name for m in milestones)

    def check(obs, state: dict) -> bool:
        return all(m.check(obs, state) for m in milestones)

    return Milestone(name=name, description=desc, check=check)


# ---------- registry ----------

_MILESTONES = {
    m.name: m for m in [
        mine_town_milestone,
        sokoban_complete_milestone,
        oracle_consult_milestone,
        quest_complete_milestone,
        castle_reached_milestone,
    ]
}


def get_milestone(name: str) -> Milestone:
    """Look up a built-in milestone by name. Raises KeyError if missing."""
    if name not in _MILESTONES:
        raise KeyError(f"No milestone named '{name}'. Available: {sorted(_MILESTONES)}")
    return _MILESTONES[name]


def list_milestones() -> list[str]:
    return sorted(_MILESTONES.keys())
