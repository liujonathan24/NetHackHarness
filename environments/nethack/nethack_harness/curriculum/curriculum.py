"""
nethack_harness.curriculum.curriculum
=======================

Smooth difficulty ramp over native NetHack tasks.

Each tier returns a configured NetHackCoreEnv-compatible env spec driven by the
fork engine via native NetHack tasks (NetHackScore-v0). The former MiniHack
des-file tiers (empty_room / solo_combat / multi_combat) were removed along with
the nle/minihack dependencies; bespoke starting states are now expressed via
saved-level blobs instead.

Tiers (easy -> hard):
    corridor_explore  -- reach dlvl 2
    mini_dungeon      -- reach dlvl 3
    mines_to_minetown / sokoban_complete / oracle_consult -- branch milestones
    full_dungeon_easy -- reach dlvl 6
    full_nle          -- the full game; ascend
    quest_complete / castle_reached -- long-horizon endgame milestones
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from .milestones import (
    Milestone,
    castle_reached_milestone,
    mine_town_milestone,
    oracle_consult_milestone,
    quest_complete_milestone,
    reach_dlvl_milestone,
    sokoban_complete_milestone,
)


TierName = Literal[
    "corridor_explore", "mini_dungeon",
    "mines_to_minetown", "sokoban_complete", "oracle_consult",
    "full_dungeon_easy", "full_nle",
    "dynamic_subgoal",
    "quest_complete", "castle_reached",
]


@dataclass(frozen=True)
class TierSpec:
    name: str
    nle_task: str               # native NetHack gym id (e.g. NetHackScore-v0)
    des_file: Optional[str]     # always None now (MiniHack des-file path removed)
    max_episode_steps: int
    description: str
    success_criterion: str      # human-readable, codified in rubric
    # Milestone-driven success. If set, env_response checks this every step
    # and treats a True return as a positive termination.
    success_milestone: Optional[Milestone] = None


TIERS: dict[TierName, TierSpec] = {
    "corridor_explore": TierSpec(
        name="corridor_explore",
        nle_task="NetHackScore-v0",
        des_file=None,
        max_episode_steps=2_000,
        description="Reach dungeon level 2: explore until you find stairs DOWN (`>`), step onto them, then call `descend`.",
        success_criterion="reached dungeon level 2",
        success_milestone=reach_dlvl_milestone(2),
    ),
    "mini_dungeon": TierSpec(
        name="mini_dungeon",
        nle_task="NetHackScore-v0",
        des_file=None,
        max_episode_steps=4_000,
        description="Reach dungeon level 3 by repeatedly finding `>` stairs and calling `descend`.",
        success_criterion="reached dungeon level 3",
        success_milestone=reach_dlvl_milestone(3),
    ),
    "mines_to_minetown": TierSpec(
        name="mines_to_minetown",
        nle_task="NetHackScore-v0",
        des_file=None,
        max_episode_steps=8_000,
        description="Find the Gnomish Mines branch and reach Mine Town.",
        success_criterion="reached Mine Town",
        success_milestone=mine_town_milestone,
    ),
    "sokoban_complete": TierSpec(
        name="sokoban_complete",
        nle_task="NetHackScore-v0",
        des_file=None,
        max_episode_steps=10_000,
        description="Solve the Sokoban puzzle branch.",
        success_criterion="completed Sokoban",
        success_milestone=sokoban_complete_milestone,
    ),
    "oracle_consult": TierSpec(
        name="oracle_consult",
        nle_task="NetHackScore-v0",
        des_file=None,
        max_episode_steps=8_000,
        description="Find and pay the Oracle of Delphi for a consultation.",
        success_criterion="consulted the Oracle",
        success_milestone=oracle_consult_milestone,
    ),
    "full_dungeon_easy": TierSpec(
        name="full_dungeon_easy",
        nle_task="NetHackScore-v0",
        des_file=None,
        max_episode_steps=10_000,
        description="Standard NetHack with reduced max depth.",
        success_criterion="reached dungeon level 6",
        success_milestone=reach_dlvl_milestone(6),
    ),
    "full_nle": TierSpec(
        name="full_nle",
        nle_task="NetHackScore-v0",
        des_file=None,
        max_episode_steps=100_000,
        description="The full game. Ascend.",
        success_criterion="ascended",
        # success is detected via ascension_reward + _detect_terminal_outcome
        # rather than a milestone; no success_milestone here.
    ),
    "dynamic_subgoal": TierSpec(
        name="dynamic_subgoal",
        nle_task="NetHackScore-v0",
        des_file=None,
        max_episode_steps=4_000,
        description="LLM-proposed subgoal each episode. The 'autoresearch' axis: a "
                    "proposer LLM (or OfflineSubgoalProposer for tests) reads the agent's "
                    "role + initial obs and emits a structured subgoal; the env compiles "
                    "its termination_check into a Milestone and runs against it.",
        success_criterion="LLM-proposed subgoal achieved",
        # success_milestone is set per-rollout in env.setup_state, not statically.
    ),
    "quest_complete": TierSpec(
        name="quest_complete",
        nle_task="NetHackScore-v0",
        des_file=None,
        max_episode_steps=20_000,
        description="Reach and complete your role's quest. Long-horizon: requires "
                    "navigating to the quest portal (dlvl ~14-19) and surviving.",
        success_criterion="completed the role quest, picked up the quest artifact",
        success_milestone=quest_complete_milestone,
    ),
    "castle_reached": TierSpec(
        name="castle_reached",
        nle_task="NetHackScore-v0",
        des_file=None,
        max_episode_steps=30_000,
        description="Reach the Castle (dlvl ~25-29) in the main dungeon. The "
                    "step before Gehennom; a real endgame milestone.",
        success_criterion="entered the Castle",
        success_milestone=castle_reached_milestone,
    ),
}


def get_tier(name: str) -> TierSpec:
    if name not in TIERS:
        raise KeyError(f"No tier named '{name}'. Available: {sorted(TIERS)}")
    return TIERS[name]


def list_tiers() -> list[str]:
    return list(TIERS.keys())


def sample_tier(weights: Optional[dict[TierName, float]] = None) -> TierName:
    """
    Sample a tier for curriculum training. Default: uniform across all tiers.
    Pass `weights` to skew (e.g. focus on harder tiers as training progresses).

    TODO(jonathan): Wire this to a difficulty buffer like wiki_search does --
    sample tiers inversely proportional to current success rate.
    """
    import random
    if weights is None:
        return random.choice(list(TIERS.keys()))
    names, probs = zip(*weights.items())
    return random.choices(names, weights=probs, k=1)[0]
