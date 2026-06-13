"""mc_replay — Monte-Carlo lookahead / branch tool over the fork NetHack engine.

Built on EngineEnv's in-memory snapshot / restore / reseed primitives
(see ``nethack_core/engine_env.py`` and ``nethack_core/_engine.py``).
"""

from .core import mc_lookahead, replay_then_branch

__all__ = ["mc_lookahead", "replay_then_branch"]
