"""Smoke tests: every module imports cleanly and the registered skills/tiers
match expectations. Catches issues like stale references after refactors.
"""
from __future__ import annotations

import importlib
import pytest


CORE_MODULES = [
    "nethack_core.env",
    "nethack_core.observations",
    "nethack_harness.tools.skills",
    "nethack_harness.memory.journal",
    "nethack_harness.navigation.pathfinding",
    "nethack_harness.curriculum.milestones",
    "nethack_harness.curriculum.curriculum",
    "legacy.replay",
    "nethack_harness.tools.wiki",
    "nethack_harness.tools.code_mode",
    "nethack_harness.curriculum.subgoals",
    "legacy.puffer_env",
]

ENV_MODULES = [
    "nethack",
]


@pytest.mark.parametrize("name", CORE_MODULES + ENV_MODULES)
def test_import(name):
    importlib.import_module(name)


def test_expected_skills_registered():
    from nethack_harness.tools.skills import list_skills

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
    from nethack_harness.curriculum.curriculum import list_tiers

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
    from nethack_harness.curriculum.subgoals import OfflineSubgoalProposer

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


def test_nethack_core_is_extraction_only():
    """nethack_core is now the extraction substrate only: env + observations.

    Everything else (skills, prompt, curriculum, navigation, memory) moved into
    the nethack_harness package; replay/puffer_env are parked in legacy/.
    """
    import nethack_core
    assert hasattr(nethack_core, "observations"), "observations should be exposed"
    for typ in ("CoreObservation", "EpisodeMetadata", "NetHackCoreEnv"):
        assert hasattr(nethack_core, typ), f"missing type: {typ}"
    # The non-extraction modules must NOT hang off nethack_core anymore.
    for moved in ("skills", "curriculum", "pathfinding", "journal", "milestones"):
        assert not hasattr(nethack_core, moved), f"{moved} should have moved to nethack_harness"
    # And they should be importable from their new homes.
    from nethack_harness.tools.skills import registry  # noqa: F401
    from nethack_harness.curriculum.curriculum import get_tier  # noqa: F401
    from nethack_harness.navigation.pathfinding import find_frontiers  # noqa: F401
    from nethack_harness.memory.journal import Journal  # noqa: F401
