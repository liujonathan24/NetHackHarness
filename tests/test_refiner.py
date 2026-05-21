"""
Tests for the Continual-Harness Refiner (variant=CH).

Run with: uv run pytest tests/test_refiner.py -v
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from nethack_core.journal import Journal
from nethack_core.refiner import (
    MacroStep,
    OfflineRefiner,
    RefinerEdits,
    SubagentSpec,
    _parse_edits,
    apply_edits,
    load_components,
    snapshot_components,
    trigger_fires,
)


# ---------- OfflineRefiner ----------

def test_offline_refiner_is_noop():
    edits = OfflineRefiner().refine(window=[{"role": "user", "content": "anything"}], components={})
    assert edits.is_noop()


# ---------- apply_edits ----------

def _fresh_state():
    return {"journal": Journal()}


def test_apply_edits_sets_prompt_addendum():
    state = _fresh_state()
    apply_edits(state, RefinerEdits(prompt_addendum="  watch HP carefully  "))
    assert state["_ch_prompt_addendum"] == "watch HP carefully"


def test_apply_edits_subagent_crud():
    state = _fresh_state()
    apply_edits(state, RefinerEdits(subagents_set={
        "low_hp": SubagentSpec(trigger="hp_pct<0.4", text="retreat and pray"),
    }))
    assert "low_hp" in state["_ch_subagents"]
    assert state["_ch_subagents"]["low_hp"]["trigger"] == "hp_pct<0.4"
    apply_edits(state, RefinerEdits(subagents_delete=["low_hp"]))
    assert "low_hp" not in state["_ch_subagents"]


def test_apply_edits_skill_macro_validates_against_registry():
    """Macros referencing unknown skill names get dropped silently."""
    state = _fresh_state()
    apply_edits(state, RefinerEdits(skills_set={
        "find_stairs": [
            MacroStep(skill="autoexplore", args={}),
            MacroStep(skill="this_skill_does_not_exist", args={}),
            MacroStep(skill="descend", args={}),
        ],
    }))
    macro = state["_ch_skills"].get("find_stairs")
    assert macro is not None
    # The fake skill should have been stripped.
    skill_names = [s["skill"] for s in macro]
    assert "this_skill_does_not_exist" not in skill_names
    assert "autoexplore" in skill_names and "descend" in skill_names


def test_apply_edits_journal_notes_and_objective():
    state = _fresh_state()
    apply_edits(state, RefinerEdits(
        notes_set={"shop:dlvl3": "scrolls 200gp"},
        objective="reach dlvl 5",
    ))
    j: Journal = state["journal"]
    assert "shop:dlvl3" in j.notes
    assert j.objective == "reach dlvl 5"
    apply_edits(state, RefinerEdits(notes_delete=["shop:dlvl3"]))
    assert "shop:dlvl3" not in j.notes


# ---------- _parse_edits (LLM output) ----------

def test_parse_edits_strips_code_fences():
    raw = "```json\n{\"prompt_addendum\": \"hello\"}\n```"
    edits = _parse_edits(raw)
    assert edits.prompt_addendum == "hello"


def test_parse_edits_recovers_from_prose_wrapping():
    raw = "Sure! Here's the JSON:\n{\"objective\": \"go down\"}\nLet me know if..."
    edits = _parse_edits(raw)
    assert edits.objective == "go down"


def test_parse_edits_garbage_returns_noop():
    assert _parse_edits("definitely not json").is_noop()
    assert _parse_edits("").is_noop()


def test_parse_edits_drops_malformed_subagents():
    raw = '{"subagents_set": {"good": {"trigger": "always", "text": "ok"}, "bad": "not a dict"}}'
    edits = _parse_edits(raw)
    assert "good" in edits.subagents_set
    assert "bad" not in edits.subagents_set


# ---------- trigger DSL ----------

@dataclass
class _FakeObs:
    status: dict
    hostiles: list = None


def test_trigger_always_fires():
    assert trigger_fires("always", _FakeObs(status={})) is True


def test_trigger_hp_pct():
    obs = _FakeObs(status={"hitpoints": 10, "max_hitpoints": 30})
    assert trigger_fires("hp_pct<0.4", obs) is True
    assert trigger_fires("hp_pct>0.4", obs) is False


def test_trigger_unknown_field_returns_false():
    assert trigger_fires("not_a_field>5", _FakeObs(status={})) is False


def test_trigger_no_operator_returns_false():
    assert trigger_fires("hp_pct", _FakeObs(status={})) is False


def test_trigger_hostile_count():
    obs = _FakeObs(status={}, hostiles=["jackal", "newt"])
    assert trigger_fires("hostile_count>1", obs) is True
    assert trigger_fires("hostile_count>=3", obs) is False


# ---------- snapshot / load round-trip ----------

def test_snapshot_load_roundtrip():
    state = _fresh_state()
    state["journal"].pin_objective("descend to oracle")
    apply_edits(state, RefinerEdits(
        prompt_addendum="prefer safe corridors",
        subagents_set={"low_hp": SubagentSpec(trigger="hp_pct<0.3", text="retreat")},
        notes_set={"altar:dlvl2": "lawful"},
    ))
    snap = snapshot_components(state)

    new_state = _fresh_state()
    load_components(new_state, snap)
    assert new_state["_ch_prompt_addendum"] == "prefer safe corridors"
    assert "low_hp" in new_state["_ch_subagents"]
    assert new_state["journal"].notes.get("altar:dlvl2") == "lawful"
    # Objective was empty on the fresh journal, so load should fill it.
    assert new_state["journal"].objective == "descend to oracle"


# ---------- env smoke: CH variant loads without an API key ----------

def test_load_environment_ch_variant_falls_back_to_offline():
    """When variant=CH but no refiner_model is provided, we should warn and
    fall back to OfflineRefiner — not crash and not require an API key."""
    from environments.nethack.nethack import load_environment
    with pytest.warns(UserWarning, match="OfflineRefiner"):
        env = load_environment(
            tier="corridor_explore",
            n_examples=1,
            seed=42,
            max_turns=5,
            variant="CH",
            refine_interval=2,
        )
    from nethack_core.refiner import OfflineRefiner
    assert isinstance(env.refiner, OfflineRefiner)
    # run_macro tool must be exposed to the agent under variant=CH.
    tool_names = {getattr(t, "__name__", "") for t in env.tools}
    assert "run_macro" in tool_names


def test_load_environment_ch_with_explicit_refiner():
    """A pre-built refiner passed in should be used verbatim — no fallback."""
    from environments.nethack.nethack import load_environment
    sentinel = OfflineRefiner()
    env = load_environment(
        tier="corridor_explore",
        n_examples=1,
        seed=42,
        max_turns=5,
        variant="CH",
        refiner=sentinel,
    )
    assert env.refiner is sentinel
