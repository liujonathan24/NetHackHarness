"""Smoke tests: every module imports cleanly and the registered skills/tiers
match expectations. Catches issues like stale references after refactors.
"""
from __future__ import annotations

import importlib
import pytest


CORE_MODULES = [
    "nethack_core.env",
    "nethack_core.observations",
    "nethack_core.skills",
    "nethack_core.journal",
    "nethack_core.pathfinding",
    "nethack_core.milestones",
    "nethack_core.curriculum",
    "nethack_core.replay",
    "nethack_core.wiki",
    "nethack_core.code_mode",
    "nethack_core.subgoals",
    "nethack_core.puffer_env",
]

ENV_MODULES = [
    "nethack",
]


@pytest.mark.parametrize("name", CORE_MODULES + ENV_MODULES)
def test_import(name):
    importlib.import_module(name)


def test_expected_skills_registered():
    from nethack_core.skills import list_skills

    expected = {
        "move", "attack", "descend", "search", "pickup",
        "inventory_item", "menu_option", "move_to", "autoexplore",
        "add_note", "recall", "pin_objective",
        "wiki_lookup", "wiki_search",
        # Survival actions added 2026-05-15.
        "eat", "quaff", "read", "pray", "engrave_elbereth", "kick", "throw",
    }
    actual = set(list_skills())
    missing = expected - actual
    assert not missing, f"Missing skills: {missing}"


def test_expected_tiers_present():
    from nethack_core.curriculum import list_tiers

    expected = {
        "empty_room", "solo_combat", "multi_combat",
        "corridor_explore", "mini_dungeon",
        "mines_to_minetown", "sokoban_complete", "oracle_consult",
        "full_dungeon_easy", "full_nle",
        "dynamic_subgoal",
        "quest_complete", "castle_reached",
    }
    actual = set(list_tiers())
    missing = expected - actual
    assert not missing, f"Missing tiers: {missing}"


def test_load_environment_both_interfaces():
    """Smoke that both interface modes construct without error."""
    from nethack import load_environment

    e1 = load_environment(tier="corridor_explore", n_examples=1, max_turns=2, interface="skill")
    assert len(e1.tools) > 1
    e2 = load_environment(tier="corridor_explore", n_examples=1, max_turns=2, interface="code")
    assert len(e2.tools) == 1


def test_unknown_interface_raises():
    from nethack import load_environment
    with pytest.raises(ValueError, match="interface"):
        load_environment(interface="not_a_thing", n_examples=1, max_turns=2)


def test_offline_subgoal_proposer_swappable():
    """Pluggable: load_environment(subgoal_proposer=) is honored."""
    from nethack import load_environment
    from nethack_core.subgoals import OfflineSubgoalProposer

    env = load_environment(tier="corridor_explore", n_examples=1, max_turns=2,
                            subgoal_proposer=OfflineSubgoalProposer())
    assert env.subgoal_proposer is not None


def test_default_proposer_when_none():
    from nethack import load_environment
    env = load_environment(tier="corridor_explore", n_examples=1, max_turns=2)
    assert env.subgoal_proposer is None  # uses default at rollout time


def test_compaction_knobs_threaded_through():
    """load_environment should expose compaction knobs and set them on the env."""
    from nethack import load_environment
    env = load_environment(
        tier="corridor_explore", n_examples=1, max_turns=2,
        compact_obs=False, history_keep_full=10, history_drop_after=50,
        belief_state_interval=10, journal_render_max_chars=4000,
    )
    assert env.compact_obs is False
    assert env.history_keep_full == 10
    assert env.history_drop_after == 50
    assert env.belief_state_interval == 10
    assert env.journal_render_max_chars == 4000


def test_default_compaction_knobs_are_sensible():
    from nethack import load_environment
    env = load_environment(tier="corridor_explore", n_examples=1, max_turns=2)
    assert env.compact_obs is True
    assert env.history_keep_full == 5
    assert env.history_drop_after == 100
    assert env.belief_state_interval == 25
    assert env.journal_render_max_chars == 2000


def test_nethack_core_init_exposes_submodules():
    """nethack_core.__init__ should expose all 12 submodules + 3 core types."""
    import nethack_core
    for sub in ("balrog", "code_mode", "curriculum", "journal", "milestones",
                "observations", "pathfinding", "puffer_env", "replay",
                "skills", "subgoals", "wiki"):
        assert hasattr(nethack_core, sub), f"missing submodule: {sub}"
    for typ in ("CoreObservation", "EpisodeMetadata", "NetHackCoreEnv"):
        assert hasattr(nethack_core, typ), f"missing type: {typ}"
    assert hasattr(nethack_core, "__all__")
    assert len(nethack_core.__all__) >= 15
