"""Tests for the live rollout stepper core (no HTTP).

Targets `LiveStepper`: the testable, keyless core that holds a
`NetHackInterface`, renders the chosen variant's per-turn dict (the shape
`render_turn` consumes), and advances exactly one turn on a manual action.
"""
from __future__ import annotations

from tools.rollout_view.live_server import LiveStepper


def test_manual_step_advances_one_turn(make_core_env):
    from nethack_interface import NetHackInterface, RawAction

    stepper = LiveStepper(NetHackInterface(make_core_env()))
    t0 = stepper.current_turn()  # initial obs
    assert "rendered_user_content" in t0 and "raw_grid" in t0
    assert isinstance(t0["raw_grid"], list)
    assert t0["turn"] == 0

    stepper.step_once(RawAction(0))  # manual action, no model call
    t1 = stepper.current_turn()
    assert t1["turn"] == t0["turn"] + 1
    assert "rendered_user_content" in t1 and "raw_grid" in t1
