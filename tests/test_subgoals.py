"""Tests for dynamic-subgoal compilation + the offline proposer."""
from __future__ import annotations

import numpy as np
import pytest

from nethack_harness.curriculum.subgoals import (
    OfflineSubgoalProposer,
    SubgoalSpec,
    compile_predicate,
)


# Minimal fake-obs so tests don't need NLE.
class _Obs:
    def __init__(self, messages=None, tty_text="", status=None, glyphs=None):
        self.messages = messages or []
        self.tty_chars = self._make_tty(tty_text)
        self.status = status or {"depth": 1}
        self.glyphs = np.asarray(glyphs) if glyphs is not None else None

    @staticmethod
    def _make_tty(text: str) -> np.ndarray:
        arr = np.full((24, 80), 32, dtype=np.uint8)
        for y, line in enumerate(text.splitlines()[:24]):
            for x, ch in enumerate(line[:80]):
                arr[y, x] = ord(ch)
        return arr


# ---------- predicate compiler ----------

def test_compile_message_substring_fires_on_match():
    pred = compile_predicate({"kind": "message_substring", "text": "Mine Town"})
    assert pred.check(_Obs(messages=["Welcome to Mine Town."]), {}) is True
    assert pred.check(_Obs(messages=["You feel hungry."]), {}) is False


def test_compile_tty_substring_fires_anywhere_on_screen():
    pred = compile_predicate({"kind": "tty_substring", "text": "altar"})
    assert pred.check(_Obs(tty_text="  ----\n  |.._.| altar of Pelor\n  ----"), {}) is True
    assert pred.check(_Obs(tty_text="  ----\n  |...|\n  ----"), {}) is False


def test_compile_dlvl_at_least():
    pred = compile_predicate({"kind": "dlvl_at_least", "n": 3})
    assert pred.check(_Obs(status={"depth": 4}), {}) is True
    assert pred.check(_Obs(status={"depth": 2}), {}) is False
    assert pred.check(_Obs(status={"depth": 3}), {}) is True


def test_compile_any_glyph_visible():
    pred = compile_predicate({"kind": "any_glyph_visible", "glyphs": [42, 100]})
    g = np.zeros((21, 79), dtype=np.int32)
    g[5, 5] = 100  # 100 is in our target set
    assert pred.check(_Obs(glyphs=g), {}) is True

    g2 = np.zeros((21, 79), dtype=np.int32)
    assert pred.check(_Obs(glyphs=g2), {}) is False


def test_compile_unknown_kind_raises():
    with pytest.raises(ValueError, match="Unknown termination_check kind"):
        compile_predicate({"kind": "magical_thinking"})


def test_compile_message_substring_empty_text_never_fires():
    """Defensive: empty text shouldn't match every message."""
    pred = compile_predicate({"kind": "message_substring", "text": ""})
    assert pred.check(_Obs(messages=["anything"]), {}) is False


# ---------- offline proposer ----------

def test_offline_proposer_role_dispatch():
    p = OfflineSubgoalProposer()
    monk = p.propose("monk")
    assert isinstance(monk, SubgoalSpec)
    assert "altar" in monk.objective.lower()
    assert monk.termination_check["kind"] == "tty_substring"


def test_offline_proposer_unknown_role_falls_back():
    p = OfflineSubgoalProposer()
    spec = p.propose("priestess_of_an_unknown_god")
    assert spec.termination_check == {"kind": "dlvl_at_least", "n": 2}


def test_offline_proposer_specs_compile():
    """Every default spec must produce a working compiled predicate."""
    p = OfflineSubgoalProposer()
    for role in ("monk", "valkyrie", "wizard", "samurai", "unknown"):
        spec = p.propose(role)
        pred = compile_predicate(spec.termination_check)
        # Smoke: does not raise.
        assert pred.check(_Obs(), {}) in (True, False)


# ---------- end-to-end: dynamic_subgoal tier wires through env ----------

def test_load_environment_accepts_custom_proposer():
    """Pluggable proposer: a custom SubgoalProposer is honored when passed
    via load_environment(subgoal_proposer=...).
    """
    import asyncio

    from nethack import load_environment
    from nethack_harness.curriculum.subgoals import SubgoalProposer, SubgoalSpec

    class _AlwaysAltar(SubgoalProposer):
        def propose(self, role, obs=None, max_dlvl=5):
            return SubgoalSpec(
                objective="custom: find an altar",
                termination_check={"kind": "tty_substring", "text": "altar"},
                rationale="custom proposer",
            )

    env = load_environment(tier="dynamic_subgoal", n_examples=1, max_turns=2,
                            subgoal_proposer=_AlwaysAltar())
    state = {"task": {"tier": "dynamic_subgoal", "seed": 1}}
    state = asyncio.new_event_loop().run_until_complete(env.setup_state(state))

    assert state["dynamic_subgoal"]["objective"] == "custom: find an altar"
    state["env"].close()


def test_dynamic_subgoal_tier_compiles_and_pins_objective():
    """Loading the env with tier='dynamic_subgoal' should run the proposer
    and stamp a per-rollout success_milestone into state['spec']."""
    import asyncio

    from nethack import load_environment

    env = load_environment(tier="dynamic_subgoal", n_examples=1, max_turns=2)
    state = {"task": {"tier": "dynamic_subgoal", "seed": 42}}
    state = asyncio.new_event_loop().run_until_complete(env.setup_state(state))

    assert "dynamic_subgoal" in state
    assert "objective" in state["dynamic_subgoal"]
    # The objective should be pinned into the journal for the agent to see.
    assert state["journal"].objective == state["dynamic_subgoal"]["objective"]
    # spec.success_milestone should be a real callable Milestone.
    assert state["spec"].success_milestone is not None
    state["env"].close()
