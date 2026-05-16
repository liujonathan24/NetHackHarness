"""
nethack_core
============

Interface-agnostic NetHack training substrate. Wrap once, use anywhere:
verifiers, PufferLib, Sample Factory, raw scripts.

Quick start:

    from nethack_core.env import NetHackCoreEnv
    from nethack_core import observations, skills, curriculum

    env = NetHackCoreEnv(task_name="NetHackChallenge-v0")
    env.seed(core=42, disp=42)
    obs, meta = env.reset()
    structured = observations.shape(obs, character={"role": "unknown"})

Or with curriculum:

    spec = curriculum.get_tier("solo_combat")
    env = NetHackCoreEnv(task_name=spec.nle_task, max_episode_steps=spec.max_episode_steps)
"""

from .env import CoreObservation, EpisodeMetadata, NetHackCoreEnv
from . import (
    balrog,
    code_mode,
    curriculum,
    journal,
    milestones,
    observations,
    pathfinding,
    puffer_env,
    replay,
    skills,
    subgoals,
    wiki,
)

__all__ = [
    # Core env types
    "CoreObservation",
    "EpisodeMetadata",
    "NetHackCoreEnv",
    # Submodules (use `nethack_core.<name>.<thing>` style)
    "balrog",
    "code_mode",
    "curriculum",
    "journal",
    "milestones",
    "observations",
    "pathfinding",
    "puffer_env",
    "replay",
    "skills",
    "subgoals",
    "wiki",
]
