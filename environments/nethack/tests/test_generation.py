"""Pillar 2 — map-generation knobs applied at start (tune-at-start).

Generation knobs are reset-time: they only matter while a level is being built,
and the starting level is generated inside nle_start before the binding could
call set_tune(). RawEngine.start(..., tune={...}) applies the overrides BEFORE
the starting level's mklev(), so generation knobs reshape the starting floor.
This also makes them testable at the starting level with no in-game descent.

room_density caps the number of rooms (1.0 = vanilla; the natural count is
space-limited, so values below it thin the level out).
"""
import numpy as np

from nethack_core import _engine


def _floor_cells(**tune):
    """Floor-tile count of the (revealed) starting level for the given knobs."""
    env = _engine.RawEngine()
    env.start(core=42, disp=42, tune={"reveal_map": 1.0, **tune})
    for _ in range(3):
        env.step(106)  # j — let vision/reveal settle
    n = int((env.chars == ord(".")).sum())
    env.end()
    return n


def test_tune_at_start_applies_before_generation():
    """A knob passed to start() is in effect before the first step."""
    env = _engine.RawEngine()
    env.start(core=42, disp=42, tune={"room_density": 0.05})
    assert env.get_tune()["room_density"] == 0.05
    env.end()


def test_room_density_thins_the_floor():
    """Low room_density generates a sparser starting floor than vanilla."""
    vanilla = _floor_cells(room_density=1.0)
    sparse = _floor_cells(room_density=0.05)
    assert sparse < vanilla, (
        f"room_density=0.05 floor ({sparse}) not sparser than vanilla ({vanilla})"
    )
    # Deterministic for a fixed seed.
    assert _floor_cells(room_density=0.05) == sparse


def test_room_density_one_matches_unset():
    """room_density=1.0 reproduces the vanilla generator (no parity drift)."""
    assert _floor_cells(room_density=1.0) == _floor_cells()


def test_unknown_start_knob_raises():
    env = _engine.RawEngine()
    import pytest

    with pytest.raises(KeyError):
        env.start(core=42, disp=42, tune={"not_a_real_knob": 1.0})
    env.end()
