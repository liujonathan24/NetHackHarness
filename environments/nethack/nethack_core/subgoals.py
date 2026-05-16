"""nethack_core.subgoals
========================

Dynamic subgoal curriculum: instead of hard-coded milestones (mine_town,
sokoban, oracle), let an LLM propose a subgoal at episode start given the
wiki + initial observation + agent role. The proposer LLM emits a structured
subgoal that the env compiles into a callable termination predicate, and
runs the rollout against it.

This is the autoresearch axis from the project plan: "can an LLM design its
own NetHack curriculum, given the wiki?"

The API:

    proposer = OfflineSubgoalProposer()  # or your prime-rl-backed proposer
    spec = proposer.propose(role="monk", obs=structured_obs, max_dlvl=3)
    # spec: {"objective": "...", "termination_check": {"kind": "...", ...}}
    pred = compile_predicate(spec["termination_check"])
    # pred(obs, state) -> bool, callable each step

Termination check kinds:
  - "message_substring": fires when `text` appears in `obs.messages`.
  - "tty_substring": fires when `text` appears anywhere in `obs.tty_chars`.
  - "dlvl_at_least": fires when `obs.status['depth'] >= n`.
  - "any_glyph_visible": fires when any of `glyphs` (ints) appears in
    `obs.glyphs` (the rendered map).

Add new kinds in `_PREDICATE_BUILDERS`. Keep them intentionally narrow —
the proposer LLM only needs to learn this small DSL.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

import numpy as np

from .milestones import Milestone


# ---------- Predicate compiler ----------


def _check_message_substring(spec: dict) -> Callable[[Any, dict], bool]:
    text = spec.get("text", "")
    text_l = text.lower()
    if not text:
        return lambda obs, state: False

    def _check(obs, state) -> bool:
        msgs = getattr(obs, "messages", None) or []
        return any(text_l in (m or "").lower() for m in msgs)
    return _check


def _check_tty_substring(spec: dict) -> Callable[[Any, dict], bool]:
    text = spec.get("text", "")
    text_l = text.lower()
    if not text:
        return lambda obs, state: False
    pattern = re.compile(re.escape(text_l))

    def _check(obs, state) -> bool:
        tty = getattr(obs, "tty_chars", None)
        if tty is None:
            return False
        rendered = "\n".join(
            "".join(chr(c) for c in row) for row in tty
        ).lower()
        return bool(pattern.search(rendered))
    return _check


def _check_dlvl_at_least(spec: dict) -> Callable[[Any, dict], bool]:
    n = int(spec.get("n", 2))

    def _check(obs, state) -> bool:
        status = getattr(obs, "status", None) or {}
        return int(status.get("depth", 1)) >= n
    return _check


def _check_any_glyph_visible(spec: dict) -> Callable[[Any, dict], bool]:
    glyphs = set(int(g) for g in spec.get("glyphs", []))
    if not glyphs:
        return lambda obs, state: False

    def _check(obs, state) -> bool:
        g = getattr(obs, "glyphs", None)
        if g is None:
            return False
        # obs.glyphs is the visible map; any cell == any of the targets.
        arr = np.asarray(g)
        return bool(np.isin(arr, list(glyphs)).any())
    return _check


_PREDICATE_BUILDERS = {
    "message_substring": _check_message_substring,
    "tty_substring": _check_tty_substring,
    "dlvl_at_least": _check_dlvl_at_least,
    "any_glyph_visible": _check_any_glyph_visible,
}


def compile_predicate(spec: dict) -> Milestone:
    """Compile a termination_check dict into a Milestone.

    Raises ValueError if `kind` is unknown — surfaces proposer mistakes
    immediately rather than silently returning a never-firing predicate.
    """
    kind = spec.get("kind")
    if kind not in _PREDICATE_BUILDERS:
        raise ValueError(f"Unknown termination_check kind={kind!r}; expected one of {list(_PREDICATE_BUILDERS)}")
    fn = _PREDICATE_BUILDERS[kind](spec)
    return Milestone(name=f"dynamic:{kind}", description=str(spec), check=fn)


# ---------- Subgoal proposer (sub-LM backend) ----------


@dataclass
class SubgoalSpec:
    """The structured output the proposer returns, ready for env consumption."""
    objective: str
    termination_check: dict[str, Any]
    rationale: str = ""


class SubgoalProposer:
    """Abstract: propose(role, obs, ...) -> SubgoalSpec. Subclass for your LM."""
    def propose(self, role: str, obs: Optional[Any] = None, max_dlvl: int = 5) -> SubgoalSpec:
        raise NotImplementedError


class OfflineSubgoalProposer(SubgoalProposer):
    """Deterministic role→subgoal mapping. Useful for tests; replace with a
    prime-rl-backed proposer that reads wiki + obs to compose a real subgoal."""

    _DEFAULTS_BY_ROLE = {
        "monk": SubgoalSpec(
            objective="reach an altar to sacrifice for divine favor",
            termination_check={"kind": "tty_substring", "text": "altar"},
            rationale="Monks are aligned and benefit early from altar prayer.",
        ),
        "valkyrie": SubgoalSpec(
            objective="reach dungeon level 3",
            termination_check={"kind": "dlvl_at_least", "n": 3},
            rationale="Valks are sturdy; pure depth is the highest-EV early goal.",
        ),
        "wizard": SubgoalSpec(
            objective="see a fountain (for wishing later)",
            termination_check={"kind": "tty_substring", "text": "fountain"},
            rationale="Wizards depend on wand-of-wishing; fountain is one route.",
        ),
        "samurai": SubgoalSpec(
            objective="reach Mine Town",
            termination_check={"kind": "message_substring", "text": "Welcome to Mine Town"},
            rationale="Samurai lawful access to lawful Mine Town shopkeepers.",
        ),
    }
    _FALLBACK = SubgoalSpec(
        objective="reach dungeon level 2",
        termination_check={"kind": "dlvl_at_least", "n": 2},
        rationale="Fallback when role is unknown.",
    )

    def propose(self, role: str, obs: Optional[Any] = None, max_dlvl: int = 5) -> SubgoalSpec:
        return self._DEFAULTS_BY_ROLE.get((role or "").lower(), self._FALLBACK)


def default_proposer() -> SubgoalProposer:
    return OfflineSubgoalProposer()
