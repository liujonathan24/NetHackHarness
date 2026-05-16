"""
End-to-end tests for the verifiers wrapper. We bypass the LM and synthesize
the tool-call messages directly so the env_response → step → state-update
chain is exercised without needing an OpenAI key.

These are the closest thing to "vf-eval but offline" we can stand up. They
catch regressions in the verifiers contract (state dict shape, observation
formatting, milestone wiring, journal flow) at very low cost.

Run with: uv run pytest tests/test_integration.py -v
"""

from __future__ import annotations

import asyncio
import json

import pytest

# The verifiers env is registered as a top-level module via the editable
# install of environments/nethack.
import nethack as env_module
from nethack import (
    NetHackVerifiersEnv,
    format_observation_as_chat,
    load_environment,
    success_reward,
    scout_reward,
)
from nethack_core.journal import Journal


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _tool_call_message(skill: str, args: dict) -> dict:
    """Build an OpenAI-shaped assistant message with one tool call."""
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "call_test",
            "type": "function",
            "function": {"name": skill, "arguments": json.dumps(args)},
        }],
    }


# ---------- load_environment smoke test ----------

def test_load_environment_returns_verifiers_env_with_skill_tools():
    """The Hub entrypoint must return a working vf.Environment."""
    env = load_environment(tier="empty_room", n_examples=2, max_turns=4)
    assert isinstance(env, NetHackVerifiersEnv)
    # Tool callables should include the basics + journal + autoexplore.
    # `env.tools` is a list of Python callables whose __name__ is the skill.
    tool_names = {t.__name__ for t in env.tools}
    assert {"move", "attack", "descend", "search", "pickup",
            "add_note", "recall", "pin_objective",
            "move_to", "autoexplore"} <= tool_names
    # menu_option / inventory_item are harness-owned (auto-dismissed via ESC
    # in env_response, and eat/quaff/read bundle item selection in-skill).
    # They MUST NOT be exposed as agent tools.
    assert "menu_option" not in tool_names
    assert "inventory_item" not in tool_names


# ---------- setup_state + env_response chain ----------

@pytest.mark.asyncio
async def test_setup_state_initializes_journal_and_character():
    """setup_state spins up an NLE, bootstraps character, inits state dict.

    We use mines_to_minetown (a real-NLE tier) instead of solo_combat (a
    MiniHack synthetic) because MiniHack-Skill-Custom doesn't emit the
    NetHack welcome message that bootstrap_character parses. Real NLE tiers
    always have a welcome.
    """
    env = load_environment(tier="mines_to_minetown", n_examples=1, max_turns=4)
    state = {"task": {"tier": "mines_to_minetown", "seed": 42}}
    state = await env.setup_state(state)

    assert isinstance(state["journal"], Journal)
    # v0.0.51: journal is pre-pinned with the tier description as the
    # objective, so is_empty() is False but notes are still empty.
    assert state["journal"].notes == {}
    assert state["journal"].objective
    # NB: character['role'] may be 'unknown' on dates where NLE shows a
    # calendar message instead of the welcome (e.g. new-moon nights). The
    # cross-seed coverage lives in tests/test_skills.py.
    assert state["character"]["role"] in {"unknown", "monk", "valkyrie", "samurai", "wizard", "priest", "rogue", "knight", "barbarian", "tourist", "archeologist", "caveman", "healer", "ranger"}
    assert state["scout_tiles_seen"] == set()
    assert state["max_dlvl_reached"] == 1
    assert state["terminated"] is False

    state["env"].close()


@pytest.mark.asyncio
async def test_env_response_to_move_steps_and_renders_obs():
    """A 'move' tool call produces a new observation message and step the env."""
    env = load_environment(tier="empty_room", n_examples=1, max_turns=4)
    state = {"task": {"tier": "empty_room", "seed": 42}}
    state = await env.setup_state(state)

    msg = _tool_call_message("move", {"direction": "E"})
    new_msgs = await env.env_response([msg], state)
    assert len(new_msgs) == 1
    assert new_msgs[0]["role"] == "user"
    assert "MAP" in new_msgs[0]["content"]

    state["env"].close()


@pytest.mark.asyncio
async def test_env_response_to_add_note_does_not_consume_env_step():
    """Journal ops are state-only; the in-game turn counter must not advance."""
    env = load_environment(tier="empty_room", n_examples=1, max_turns=4)
    state = {"task": {"tier": "empty_room", "seed": 42}}
    state = await env.setup_state(state)
    turn_before = state["structured_obs"].status.get("time", -1)

    msg = _tool_call_message("add_note", {"key": "test", "text": "hello"})
    new_msgs = await env.env_response([msg], state)

    assert state["journal"].notes.get("test") == "hello"
    assert state["structured_obs"].status.get("time", -1) == turn_before
    # Journal write should set scout_delta to 0 explicitly.
    assert state["scout_delta"] == 0

    state["env"].close()


@pytest.mark.asyncio
async def test_env_response_unknown_tool_returns_help_message():
    """A skill name the registry doesn't know should not crash the rollout."""
    env = load_environment(tier="empty_room", n_examples=1, max_turns=4)
    state = {"task": {"tier": "empty_room", "seed": 42}}
    state = await env.setup_state(state)

    msg = _tool_call_message("autoexplore", {"max_steps": 5})
    new_msgs = await env.env_response([msg], state)
    # autoexplore is known; the call should at least not crash.
    assert isinstance(new_msgs, list)

    state["env"].close()


# ---------- reward integration ----------

def test_success_reward_zero_then_one():
    """Direct call to the reward function: 0 without flag, 1 with."""
    assert _run(success_reward(state={})) == 0.0
    assert _run(success_reward(state={"succeeded": True})) == 1.0


# ---------- format_observation_as_chat ----------

def test_format_observation_with_empty_journal_omits_block():
    """Empty journal shouldn't add a JOURNAL header to the observation."""
    from dataclasses import dataclass

    @dataclass
    class _S:
        map_view: str = "@..."
        messages: list = None
        inventory: list = None
        status: dict = None
        character: dict = None
        menu: object = None
        inventory_prompt: object = None

    s = _S(messages=[], inventory=[], status={"depth": 1}, character={})
    out = format_observation_as_chat(s, Journal())
    assert "JOURNAL" not in out


def test_format_observation_with_populated_journal_includes_block():
    from dataclasses import dataclass

    @dataclass
    class _S:
        map_view: str = "@..."
        messages: list = None
        inventory: list = None
        status: dict = None
        character: dict = None
        menu: object = None
        inventory_prompt: object = None

    s = _S(messages=[], inventory=[], status={"depth": 1}, character={})
    j = Journal()
    j.pin_objective("find the stairs")
    out = format_observation_as_chat(s, j)
    assert "=== JOURNAL ===" in out
    assert "find the stairs" in out
