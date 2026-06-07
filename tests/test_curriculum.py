"""
Tests for curriculum.py — tier spec lookup, milestone wiring, sampling.

Run with: uv run pytest tests/test_curriculum.py -v
"""

from __future__ import annotations

import pytest

from nethack_harness.curriculum.curriculum import (
    TIERS,
    TierSpec,
    get_tier,
    list_tiers,
    sample_tier,
)


def test_every_tier_has_a_consistent_name_field():
    for key, spec in TIERS.items():
        assert spec.name == key, f"tier dict key {key!r} != spec.name {spec.name!r}"


def test_get_tier_returns_specs_by_name():
    spec = get_tier("solo_combat")
    assert isinstance(spec, TierSpec)
    assert spec.nle_task.startswith("MiniHack-") or spec.nle_task.startswith("NetHack")


def test_get_tier_raises_on_unknown():
    with pytest.raises(KeyError):
        get_tier("not_a_tier")


def test_milestone_tiers_have_success_milestones_wired():
    """Tiers that promise milestone-based stopping must carry a Milestone."""
    for name in ("corridor_explore", "mini_dungeon", "mines_to_minetown",
                 "sokoban_complete", "oracle_consult", "full_dungeon_easy"):
        spec = get_tier(name)
        assert spec.success_milestone is not None, f"{name} is missing success_milestone"


def test_minihack_tiers_have_des_files():
    """The synthetic tiers we kept must still carry des-file content."""
    for name in ("empty_room", "solo_combat", "multi_combat"):
        spec = get_tier(name)
        assert spec.des_file is not None and "MAP" in spec.des_file


def test_sample_tier_returns_known_name():
    name = sample_tier()
    assert name in TIERS


def test_sample_tier_with_weights_respects_weights_deterministic():
    """A weighted call with a single non-zero key always returns that key."""
    name = sample_tier(weights={"empty_room": 1.0, "solo_combat": 0.0})
    # Because random.choices with weights=[1, 0] always returns the first.
    assert name == "empty_room"


def test_list_tiers_matches_TIERS_keys():
    assert set(list_tiers()) == set(TIERS.keys())
