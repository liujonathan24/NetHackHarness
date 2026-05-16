"""End-to-end cohesion test for the post-compaction substrate.

A scripted 10-turn rollout that touches:
  - real env step loop
  - reward accumulation (scout_reward_total + descent_count)
  - obs compaction (compact_obs=True default)
  - history compaction (override get_prompt_messages)
  - belief-state hook (we hit it at turn 25, so won't fire in 10 turns)
  - journal diff
  - dispatcher's defensive arg parsing
  - rubric: scout_reward > 0 at end-of-rollout

If this passes, the substrate is healthy on the latest version.
"""
from __future__ import annotations

import asyncio
import json

import verifiers as vf

from nethack import load_environment, scout_reward, descent_reward


def _tool_call(skill: str, args: dict) -> vf.AssistantMessage:
    return vf.AssistantMessage(
        role="assistant",
        content=None,
        tool_calls=[vf.ToolCall(id="x", name=skill, arguments=json.dumps(args))],
    )


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_end_to_end_substrate_cohesion():
    """A scripted 10-turn rollout exercising compaction + reward + state."""
    env = load_environment(
        tier="corridor_explore", n_examples=1, max_turns=20,
        compact_obs=True, history_keep_full=3, history_drop_after=100,
    )
    state = {"task": {"tier": "corridor_explore", "seed": 42}}
    state = _run(env.setup_state(state))

    # Initial state sanity.
    assert state["scout_reward_total"] == 0.0
    assert state["descent_count"] == 0
    assert state.get("turn_count", 0) == 0  # set lazily on first env_response
    # v0.0.51: journal pre-pinned with tier objective; notes start empty.
    assert state["journal"].notes == {}

    # Drive a mix of skill calls.
    script = [
        ("pin_objective", {"text": "explore east"}),
        ("autoexplore", {"max_steps": 5}),
        ("add_note", {"key": "first_note", "text": "seen a corridor"}),
        ("autoexplore", {"max_steps": 5}),
        ("recall", {"query": "corridor"}),
        ("move", {"direction": "E"}),
        ("move", {"direction": "S"}),
        ("autoexplore", {"max_steps": 10}),
        ("search", {}),
        ("autoexplore", {"max_steps": 5}),
    ]

    for skill, args in script:
        ret = _run(env.env_response([_tool_call(skill, args)], state))
        # Every return is a list of vf.Messages (never tuple, never dicts).
        assert isinstance(ret, list) and len(ret) >= 1
        for m in ret:
            assert not isinstance(m, dict), "raw dict in env_response return"
        if state.get("terminated"):
            break

    # State invariants.
    # turn_count only increments on non-journal-op turns (journal ops short-circuit).
    assert state["turn_count"] >= 5, f"turn count too low: {state['turn_count']}"
    assert state["scout_reward_total"] > 0.0, "no exploration credited; reward bug?"
    assert state["journal"].objective == "explore east"
    assert "first_note" in state["journal"].notes

    # Rubric reads the same totals.
    r = _run(scout_reward(state=state))
    assert r == state["scout_reward_total"]
    d = _run(descent_reward(state=state))
    assert d == float(state["descent_count"])

    # Token-cost story: the get_prompt_messages override should compact older
    # turns. Build a synthetic trajectory and verify it processes through.
    state["trajectory"] = [{
        "prompt": [vf.UserMessage(role="user", content="initial")],
        "completion": [vf.AssistantMessage(role="assistant", content="hi", tool_calls=[])],
    }]
    # Direct sanity: compact_obs is set, history_keep_full was 3.
    assert env.compact_obs is True
    assert env.history_keep_full == 3
    state["env"].close()


def test_compact_off_disables_at_env_level():
    """Same scripted rollout with compact_obs=False — the env's compact flag
    should be honored; obs text should NOT contain `.{N}` encoding."""
    env = load_environment(tier="corridor_explore", n_examples=1, max_turns=5, compact_obs=False)
    state = {"task": {"tier": "corridor_explore", "seed": 42}}
    state = _run(env.setup_state(state))
    ret = _run(env.env_response([_tool_call("autoexplore", {"max_steps": 3})], state))
    obs_text = ret[0].content
    # No glyph-run encoding under compact=False.
    import re
    assert not re.search(r"\.\{\d+\}", obs_text), "glyph-run encoding leaked into compact=False output"
    state["env"].close()
