"""Automated harness-iteration loop for the NetHack LLM-agent env.

A self-improving outer loop that, each iteration, (1) creates a fresh git
worktree for isolation/reproducibility, (2) runs a Continual-Harness rollout
inside it, and (3) mutates ONLY the harness (tools/skills, system prompt,
observation format) between iterations while the game engine stays IMMUTABLE.

See README.md for the immutable-game invariant and run commands.
"""

from .config import HarnessConfig
from .proposer import FallbackProposer, LLMProposer, Proposer

__all__ = ["HarnessConfig", "Proposer", "FallbackProposer", "LLMProposer"]
