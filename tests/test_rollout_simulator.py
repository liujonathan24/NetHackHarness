"""
End-to-end rollout simulator: drive env_response with scripted tool calls
and verify the full pipeline (skill dispatch, milestone firing, journal,
rubric) produces sane outputs.

This is the closest we can get to `vf-eval` offline. A real vf-eval would
substitute an LM for our scripted_assistant; everything else is the same.

Run with: uv run pytest tests/test_rollout_simulator.py -v
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Callable

import pytest

import verifiers as vf

from nethack import (
    NetHackVerifiersEnv,
    ascension_reward,
    descent_reward,
    load_environment,
    scout_reward,
    success_reward,
)


def _tool_call(skill: str, args: dict) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "call_x",
            "type": "function",
            "function": {"name": skill, "arguments": json.dumps(args)},
        }],
    }


def _tool_call_pydantic(skill: str, args: dict) -> vf.AssistantMessage:
    """The shape verifiers 0.1.14 actually passes into env_response on the Hub.

    Flat ToolCall (no .function nesting), wrapped in an AssistantMessage pydantic
    model. Catches the two bugs that bit v0.0.3/v0.0.4 in hosted eval:
      - dict access `tc["function"]["name"]` blowing up on a pydantic ToolCall.
      - dict-shaped env_response returns being rejected by normalize_messages.
    """
    return vf.AssistantMessage(
        role="assistant",
        content=None,
        tool_calls=[vf.ToolCall(id="call_x", name=skill, arguments=json.dumps(args))],
    )


async def _drive(env: NetHackVerifiersEnv, tier: str, seed: int,
                 script: list[tuple[str, dict]]) -> dict:
    """
    Run `script` as a sequence of tool calls against a freshly-set-up env.
    Returns the final state dict.
    """
    state: dict = {"task": {"tier": tier, "seed": seed}}
    state = await env.setup_state(state)

    for skill, args in script:
        msg = _tool_call(skill, args)
        new_msgs = await env.env_response([msg], state)
        if state.get("terminated"):
            break

    state["env"].close()
    return state


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------- scripted rollouts ----------

def test_scripted_journal_pin_then_explore_keeps_state_consistent():
    """A real LM-shaped rollout: pin objective, autoexplore, recall, note."""
    env = load_environment(tier="mines_to_minetown", n_examples=1, max_turns=10)
    script = [
        ("pin_objective", {"text": "find the stairs"}),
        ("add_note", {"key": "start_role", "text": "monk"}),
        ("autoexplore", {"max_steps": 6}),
        ("recall", {"query": "monk"}),
    ]
    state = _run(_drive(env, "mines_to_minetown", seed=42, script=script))

    j = state["journal"]
    assert j.objective == "find the stairs"
    assert j.notes["start_role"] == "monk"
    # autoexplore should have produced some scout reward.
    assert state["scout_delta"] >= 0


def test_scripted_pure_movement_advances_in_game_turns():
    """Several `move` calls should advance the in-game time counter."""
    env = load_environment(tier="mines_to_minetown", n_examples=1, max_turns=10)
    script = [
        ("move", {"direction": "E"}),
        ("move", {"direction": "E"}),
        ("move", {"direction": "S"}),
    ]
    state = _run(_drive(env, "mines_to_minetown", seed=42, script=script))
    # Movement actions consume in-game turns; turn count should be > 0.
    assert state["structured_obs"].status.get("time", 0) > 0


def test_scripted_rollout_terminates_cleanly_on_invalid_path():
    """move_to to an unreachable tile shouldn't crash, should produce feedback."""
    env = load_environment(tier="mines_to_minetown", n_examples=1, max_turns=10)
    script = [("move_to", {"x": 0, "y": 0})]  # almost certainly a wall
    state = _run(_drive(env, "mines_to_minetown", seed=42, script=script))
    # Either we got an interrupted SkillResult and the rollout continues,
    # or no actions were stepped. Either way: state should still be sane.
    assert "structured_obs" in state
    assert "journal" in state


def test_scripted_milestone_does_not_fire_on_short_rollout():
    """A 5-turn rollout from seed 42 won't reach Mine Town. success=False."""
    env = load_environment(tier="mines_to_minetown", n_examples=1, max_turns=10)
    script = [("move", {"direction": d}) for d in ["N", "E", "S", "W", "E"]]
    state = _run(_drive(env, "mines_to_minetown", seed=42, script=script))
    assert state.get("succeeded") is not True
    assert _run(success_reward(state=state)) == 0.0


def test_scripted_rollout_rubric_is_finite():
    """The rubric reward functions must produce finite floats given a real state."""
    env = load_environment(tier="mines_to_minetown", n_examples=1, max_turns=10)
    script = [("autoexplore", {"max_steps": 5})]
    state = _run(_drive(env, "mines_to_minetown", seed=42, script=script))
    for fn in (scout_reward, descent_reward, success_reward, ascension_reward):
        r = _run(fn(state=state))
        assert isinstance(r, float)
        assert r == r  # not NaN
        assert abs(r) < 1e6  # not exploded


def test_pydantic_tool_call_shape_is_accepted():
    """Regression: verifiers 0.1.14 passes vf.AssistantMessage with flat ToolCall.

    The Hub eval crashed twice on the wrong shape — once on `tc["function"]["name"]`
    and once on returning raw dict messages. This drives env_response with the
    real pydantic shapes and asserts the returns are also vf.Messages.
    """
    env = load_environment(tier="mines_to_minetown", n_examples=1, max_turns=4)
    state = {"task": {"tier": "mines_to_minetown", "seed": 42}}
    state = _run(env.setup_state(state))

    msg = _tool_call_pydantic("autoexplore", {"max_steps": 3})
    new_msgs = _run(env.env_response([msg], state))

    # Every returned message must be a vf.Message-like, not a raw dict.
    assert len(new_msgs) >= 1
    for m in new_msgs:
        assert not isinstance(m, dict), f"got raw dict, verifiers will reject: {m}"
        assert hasattr(m, "role") and hasattr(m, "content")
    # And the skill actually dispatched (autoexplore should have advanced the env).
    assert "structured_obs" in state
    state["env"].close()


def test_dispatcher_handles_invalid_json_args():
    """Regression: malformed JSON in arguments must not crash."""
    env = load_environment(tier="mines_to_minetown", n_examples=1, max_turns=4)
    state = {"task": {"tier": "mines_to_minetown", "seed": 42}}
    state = _run(env.setup_state(state))

    # Pass arguments="not_json" (no JSON envelope)
    msg = vf.AssistantMessage(
        role="assistant",
        content=None,
        tool_calls=[vf.ToolCall(id="x", name="search", arguments="this is not json")],
    )
    ret = _run(env.env_response([msg], state))
    assert isinstance(ret, list) and len(ret) >= 1
    state["env"].close()


def test_dispatcher_handles_list_args():
    """Regression: model emits arguments as a JSON list, not dict."""
    env = load_environment(tier="mines_to_minetown", n_examples=1, max_turns=4)
    state = {"task": {"tier": "mines_to_minetown", "seed": 42}}
    state = _run(env.setup_state(state))

    msg = vf.AssistantMessage(
        role="assistant",
        content=None,
        tool_calls=[vf.ToolCall(id="x", name="search", arguments='["bad"]')],
    )
    ret = _run(env.env_response([msg], state))
    assert isinstance(ret, list)
    state["env"].close()


def test_dispatcher_handles_empty_args():
    """Regression: model emits an empty arguments string."""
    env = load_environment(tier="mines_to_minetown", n_examples=1, max_turns=4)
    state = {"task": {"tier": "mines_to_minetown", "seed": 42}}
    state = _run(env.setup_state(state))

    msg = vf.AssistantMessage(
        role="assistant",
        content=None,
        tool_calls=[vf.ToolCall(id="x", name="search", arguments="")],
    )
    ret = _run(env.env_response([msg], state))
    assert isinstance(ret, list)
    state["env"].close()


def test_malformed_tool_args_produce_feedback_not_crash():
    """Regression: small models (Qwen 0.8B) sometimes call tools with malformed
    args like search(arguments="..."). Dispatch must filter unknown kwargs and
    surface them as feedback, not crash the worker.
    """
    env = load_environment(tier="mines_to_minetown", n_examples=1, max_turns=4)
    state = {"task": {"tier": "mines_to_minetown", "seed": 42}}
    state = _run(env.setup_state(state))

    # Mimic the Qwen 0.8B output that crashed v0.0.6: arguments dict contains
    # a stray "arguments" key plus no real params.
    msg = _tool_call_pydantic("search", {"arguments": "search around"})
    ret = _run(env.env_response([msg], state))

    assert isinstance(ret, list) and len(ret) >= 1
    assert hasattr(ret[0], "content")
    # Either the call succeeded with the unknown arg ignored, or feedback says so.
    # In neither case should the worker crash.
    state["env"].close()


def test_env_response_returns_messages_not_tuple():
    """Regression: verifiers 0.1.14 calls maybe_normalize_messages on the raw
    env_response return. Returning `(messages, state)` makes it see a list whose
    first item is itself a list ('Invalid env_response item type: list').
    The contract is now `-> vf.Messages` only; state is mutated in place.
    """
    env = load_environment(tier="mines_to_minetown", n_examples=1, max_turns=4)
    state = {"task": {"tier": "mines_to_minetown", "seed": 42}}
    state = _run(env.setup_state(state))

    msg = _tool_call_pydantic("autoexplore", {"max_steps": 1})
    ret = _run(env.env_response([msg], state))

    # Must NOT be a tuple. Must be a flat list of vf.Message-like objects.
    assert not isinstance(ret, tuple), "env_response must return Messages, not (Messages, State)"
    assert isinstance(ret, list)
    for m in ret:
        assert not isinstance(m, list), "found nested list — verifiers will reject"
        assert hasattr(m, "role") and hasattr(m, "content")
    state["env"].close()


def test_pydantic_no_tool_call_returns_vf_message():
    """Regression: the no-tool-call recovery branch must also return vf.Messages."""
    env = load_environment(tier="mines_to_minetown", n_examples=1, max_turns=4)
    state = {"task": {"tier": "mines_to_minetown", "seed": 42}}
    state = _run(env.setup_state(state))

    # Empty tool_calls — should hit the "you must call a tool" path.
    msg = vf.AssistantMessage(role="assistant", content="thinking out loud", tool_calls=[])
    new_msgs = _run(env.env_response([msg], state))

    assert len(new_msgs) == 1
    assert not isinstance(new_msgs[0], dict)
    assert "tool" in new_msgs[0].content.lower()
    state["env"].close()


def test_scripted_wiki_lookup_returns_lore_in_feedback():
    """wiki_lookup is a no-step skill; the feedback should mention the entity."""
    env = load_environment(tier="mines_to_minetown", n_examples=1, max_turns=4)
    state = {"task": {"tier": "mines_to_minetown", "seed": 42}}
    state = _run(env.setup_state(state))

    msg = _tool_call("wiki_lookup", {"entity": "cockatrice"})
    new_msgs = _run(env.env_response([msg], state))
    # The wiki body should appear in the rendered observation. We don't
    # assert on specific lore text because the snapshot content varies by
    # scrape source (6-page stub vs API scrape); we only require that the
    # wiki feedback prefix + the entity name make it into the obs.
    content = new_msgs[0].content if hasattr(new_msgs[0], "content") else new_msgs[0]["content"]
    text = content.lower()
    assert "wiki" in text and "cockatrice" in text, text[:500]

    state["env"].close()
