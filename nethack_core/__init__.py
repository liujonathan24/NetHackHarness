"""
nethack_core
============

Interface-agnostic NetHack **extraction** substrate: wrap the NetHack Learning
Environment and surface a clean observation. Everything else (skills, prompt,
curriculum, navigation, memory) lives in the ``nethack_harness`` package.

    from nethack_core.env import NetHackCoreEnv
    from nethack_core import observations

    env = NetHackCoreEnv(task_name="NetHackScore-v0")
    env.seed(core=42, disp=42)
    obs, meta = env.reset()
    structured = observations.shape(obs, character={"role": "unknown"})
"""

from .env import CoreObservation, EpisodeMetadata, NetHackCoreEnv
from . import observations

__all__ = [
    "CoreObservation",
    "EpisodeMetadata",
    "NetHackCoreEnv",
    "observations",
]
