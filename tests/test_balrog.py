"""BALROG progression score tests."""
from __future__ import annotations

import pytest

from nethack_harness.prompt.balrog import progression_score, progression_tier


def test_spawn_is_zero():
    assert progression_score(1, 1) == pytest.approx(0.0, abs=0.01)


def test_endgame_is_near_one():
    assert progression_score(53, 30) >= 0.9


def test_monotonic_in_dl():
    a = progression_score(5, 5)
    b = progression_score(10, 5)
    c = progression_score(20, 5)
    assert a < b < c


def test_monotonic_in_xl():
    a = progression_score(10, 1)
    b = progression_score(10, 10)
    c = progression_score(10, 20)
    assert a < b < c


def test_clipped_at_one():
    assert progression_score(100, 100) == 1.0


def test_floor_at_zero():
    assert progression_score(0, 0) == 0.0
    assert progression_score(-1, -1) == 0.0


def test_tier_spawn():
    assert progression_tier(0.0) == "spawn"


def test_tier_buckets():
    assert progression_tier(0.0) == "spawn"
    assert progression_tier(0.001) == "early"
    assert progression_tier(0.05) == "past_mines"
    assert progression_tier(0.3) == "midgame"
    assert progression_tier(0.8) == "endgame"


def test_midgame_calibration():
    """DL=15 XL=10 should land in midgame range (~0.05)."""
    s = progression_score(15, 10)
    assert 0.01 <= s <= 0.3, f"midgame score {s} out of expected band"
