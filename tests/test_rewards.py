"""
Tests for the reward functions in environments/nethack/nethack.py.

These hit the pure-Python reward path with synthesized state dicts — no NLE
rollout required. We test:
  * scout_reward returns the per-step DELTA, not the cumulative count
  * descent_reward fires once per new max dlvl
  * ascension_reward fires only when state["ascended"]=True
  * _detect_terminal_outcome flips state on death / ascension markers in the tty

Run with: uv run pytest tests/test_rewards.py -v
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import numpy as np
import pytest

from nethack import (
    scout_reward,
    descent_reward,
    ascension_reward,
    _detect_terminal_outcome,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@dataclass
class _FakeStructured:
    """Tiny stand-in for StructuredObservation that the reward funcs accept."""
    status: dict


@dataclass
class _FakeObs:
    tty_chars: np.ndarray


def _tty_with(text_rows: list[str]) -> np.ndarray:
    arr = np.full((24, 80), ord(" "), dtype=np.uint8)
    for i, row in enumerate(text_rows[:24]):
        for j, ch in enumerate(row[:80]):
            arr[i, j] = ord(ch)
    return arr


# ---------- scout_reward ----------

def test_scout_reward_returns_delta_not_cumulative():
    """The bug we fixed: returning cumulative count rewards standing still."""
    state = {"scout_delta": 7}
    r = _run(scout_reward(state=state))
    assert r == pytest.approx(0.007)  # 7 / 1000


def test_scout_reward_zero_when_no_new_tiles():
    state = {"scout_delta": 0, "scout_tiles_seen": {("a", 0, 0), ("a", 1, 0)}}
    r = _run(scout_reward(state=state))
    assert r == 0.0


def test_scout_reward_zero_when_state_missing():
    """Defensive: never KeyError on a partial state dict."""
    r = _run(scout_reward(state={}))
    assert r == 0.0


# ---------- descent_reward ----------

def test_descent_reward_fires_once_per_new_max_dlvl():
    state = {
        "max_dlvl_reached": 1,
        "structured_obs": _FakeStructured(status={"depth": 2}),
    }
    assert _run(descent_reward(state=state)) == 1.0
    assert state["max_dlvl_reached"] == 2
    # Second call on the same dlvl: no reward.
    assert _run(descent_reward(state=state)) == 0.0


def test_descent_reward_zero_when_going_up():
    """Climbing back up should not pay out a second time."""
    state = {
        "max_dlvl_reached": 5,
        "structured_obs": _FakeStructured(status={"depth": 3}),
    }
    assert _run(descent_reward(state=state)) == 0.0


# ---------- ascension_reward ----------

def test_ascension_reward_only_on_ascended_flag():
    assert _run(ascension_reward(state={"ascended": False})) == 0.0
    assert _run(ascension_reward(state={"ascended": True})) == 1.0
    # Default state: no flag means no reward.
    assert _run(ascension_reward(state={})) == 0.0


# ---------- _detect_terminal_outcome ----------

def test_detect_terminal_outcome_marks_death_from_tty():
    obs = _FakeObs(tty_chars=_tty_with(["Goodbye Agent the Candidate...",
                                         "You died.  You were killed by a small kobold."]))
    state: dict = {}
    _detect_terminal_outcome(obs, state)
    assert state["died"] is True
    assert state["terminated"] is True
    assert state["ascended"] is False


def test_detect_terminal_outcome_marks_ascension():
    obs = _FakeObs(tty_chars=_tty_with(["You offered the Amulet to your god",
                                         "You ascended to demigod status!"]))
    state: dict = {}
    _detect_terminal_outcome(obs, state)
    assert state["ascended"] is True
    assert state["terminated"] is True
    assert state["died"] is False


def test_detect_terminal_outcome_idempotent_when_already_set():
    """If we already decided the outcome, leave it alone (absorbing state)."""
    obs = _FakeObs(tty_chars=_tty_with(["You died.  You were killed by a newt."]))
    state = {"ascended": True, "died": False, "terminated": True}
    _detect_terminal_outcome(obs, state)
    assert state["ascended"] is True  # not overwritten
    assert state["died"] is False


def test_detect_terminal_outcome_noop_on_live_game():
    obs = _FakeObs(tty_chars=_tty_with(["You see here a pile of gold."]))
    state: dict = {}
    _detect_terminal_outcome(obs, state)
    assert state["died"] is False
    assert state["ascended"] is False
    assert state.get("terminated", False) is False
