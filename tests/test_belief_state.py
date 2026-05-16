"""Periodic belief-state summary: triggered every BELIEF_STATE_INTERVAL turns
via the SubLM. Substrate that lets history-compaction drop very old turns
without losing the LM's mental model.
"""
from __future__ import annotations

import asyncio

import verifiers as vf

from nethack import BELIEF_STATE_INTERVAL, _maybe_belief_state_summary, load_environment
from nethack_core.code_mode import OfflineSubLM, SubLM
from nethack_core.journal import Journal


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _tool_call(skill: str, args: dict):
    import json
    return vf.AssistantMessage(
        role="assistant",
        content=None,
        tool_calls=[vf.ToolCall(id="x", name=skill, arguments=json.dumps(args))],
    )


def test_belief_state_summary_writes_to_journal():
    """Direct call to _maybe_belief_state_summary should add a belief_state:tN note."""
    state = {
        "journal": Journal(),
        "turn_count": 25,
        "structured_obs": type("S", (), {"status": {"hitpoints": 8, "max_hitpoints": 10, "depth": 1, "time": 25}})(),
    }
    state["journal"].add_note("strategy", "explore E first")
    _maybe_belief_state_summary(state)
    keys = list(state["journal"].notes.keys())
    assert any(k.startswith("belief_state:t") for k in keys), f"no belief_state note in {keys}"


def test_belief_state_summary_respects_custom_sublm():
    """If state['sub_lm'] is set, it should be used in preference to default."""
    class _Echo(SubLM):
        def summarize(self, text, query=None):
            return "ECHO:" + (query or "")
        def plan(self, *a, **k): raise NotImplementedError
        def recall(self, *a, **k): raise NotImplementedError
    state = {
        "journal": Journal(),
        "turn_count": 50,
        "sub_lm": _Echo(),
        "structured_obs": type("S", (), {"status": {"hitpoints": 5, "max_hitpoints": 10}})(),
    }
    _maybe_belief_state_summary(state)
    note_values = list(state["journal"].notes.values())
    assert any(v.startswith("ECHO:") for v in note_values)


def test_belief_state_does_not_break_on_failing_sublm():
    """Best-effort: a SubLM that raises must not crash the rollout."""
    class _Broken(SubLM):
        def summarize(self, *a, **k): raise RuntimeError("nope")
        def plan(self, *a, **k): raise NotImplementedError
        def recall(self, *a, **k): raise NotImplementedError
    state = {
        "journal": Journal(),
        "turn_count": 25,
        "sub_lm": _Broken(),
        "structured_obs": type("S", (), {"status": {}})(),
    }
    # Must not raise.
    _maybe_belief_state_summary(state)


def test_belief_state_interval_is_sane():
    assert 5 <= BELIEF_STATE_INTERVAL <= 100, f"interval {BELIEF_STATE_INTERVAL} out of sane range"


def test_belief_state_fires_during_real_rollout_at_interval():
    """End-to-end: after BELIEF_STATE_INTERVAL env_response calls, the
    rollout's journal should contain a belief_state note."""
    env = load_environment(tier="corridor_explore", n_examples=1, max_turns=BELIEF_STATE_INTERVAL + 3)
    state = {"task": {"tier": "corridor_explore", "seed": 42}}
    state = _run(env.setup_state(state))
    for _ in range(BELIEF_STATE_INTERVAL):
        _run(env.env_response([_tool_call("move", {"direction": "E"})], state))
        if state.get("terminated"):
            break
    keys = list(state["journal"].notes.keys())
    assert any(k.startswith("belief_state:t") for k in keys), (
        f"expected at least one belief_state:tN note after {BELIEF_STATE_INTERVAL} turns; got {keys}"
    )
    state["env"].close()
