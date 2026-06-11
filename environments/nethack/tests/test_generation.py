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


# --- remaining Pillar 2 generation knobs (level-replay) --------------------
NEW_GEN_KNOBS = [
    "mob_spawn", "trap_density", "locked_door", "corridor_connectivity", "room_size",
]


def test_new_generation_knobs_settable_and_safe():
    """Each new generation knob is settable at start across its range (incl. the
    0.0 edge) and the floor still generates without crashing; the value round-trips.
    Effects are mostly off-screen, so this is a settability + safety contract."""
    for knob in NEW_GEN_KNOBS:
        for val in (0.0, 0.5, 1.0, 1.5, 3.0):
            env = _engine.RawEngine()
            env.start(core=42, disp=42, tune={knob: val})
            assert env.get_tune()[knob] == val, f"{knob}={val} did not round-trip"
            for _ in range(2):
                env.step(46)  # '.' wait — floor exists, engine steps without crash
            assert env.chars is not None
            env.end()


def test_new_generation_knobs_one_matches_unset():
    """At 1.0 every new knob reproduces the vanilla generator (GATE A parity)."""
    base = _floor_cells()
    for knob in NEW_GEN_KNOBS:
        assert _floor_cells(**{knob: 1.0}) == base, f"{knob}=1.0 drifted from vanilla"
