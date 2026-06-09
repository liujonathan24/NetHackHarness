"""The NetPlay skill_set profile (Jeurissen, CoG 2024): high-level skill-only
action surface used as the standardized action set for cross-encoding benchmarks.
"""
from nethack_harness.helpers import _build_skill_adapter_callables

NETPLAY_EXPECTED = {
    "move_to", "autoexplore", "find_and_descend", "explore_and_descend",
    "attack", "descend", "search", "pickup", "engrave_elbereth", "pray", "eat",
    "quaff", "read", "kick", "add_note", "recall", "pin_objective",
    "wiki_lookup", "wiki_search",
}


def _names(skill_set):
    return {c.__name__ for c in _build_skill_adapter_callables(skill_set=skill_set)}


def test_netplay_profile_exposes_the_paper_action_set():
    assert _names("netplay") == NETPLAY_EXPECTED


def test_netplay_drops_low_level_move_but_keeps_pathfinding():
    names = _names("netplay")
    assert "move" not in names  # NetPlay has no low-level move(direction) primitive
    assert {"move_to", "autoexplore", "find_and_descend"} <= names
    # harness-owned skills are never exposed
    assert "menu_option" not in names and "inventory_item" not in names


def test_netplay_differs_from_full_and_move():
    assert _names("netplay") != _names("full")
    assert _names("netplay") != _names("move")
