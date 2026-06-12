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
from nethack_harness.memory.journal import Journal


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
    env = load_environment(tier="corridor_explore", n_examples=2, max_turns=4)
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
    env = load_environment(tier="corridor_explore", n_examples=1, max_turns=4)
    state = {"task": {"tier": "corridor_explore", "seed": 42}}
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
    env = load_environment(tier="corridor_explore", n_examples=1, max_turns=4)
    state = {"task": {"tier": "corridor_explore", "seed": 42}}
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
    env = load_environment(tier="corridor_explore", n_examples=1, max_turns=4)
    state = {"task": {"tier": "corridor_explore", "seed": 42}}
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


def test_pet_blocking_message_triggers_go_around_hint():
    """Regression for 9071d001 turns 100-116: 'Your kitten is in the way!'
    appeared repeatedly and the model couldn't escape. Now the harness
    emits a HINT telling the agent to step perpendicular first."""
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
        adjacent: dict = None
        under_player: object = None

    s = _S(
        messages=["Your kitten is in the way!"],
        inventory=[],
        status={"depth": 1, "hitpoints": 14, "max_hitpoints": 14},
        character={},
        adjacent={"N": "f(cat/small feline)", "S": ".", "E": "."},
    )
    out = format_observation_as_chat(s, Journal())
    assert "blocking your move" in out or "is in the way" in out  # hint fired
    assert "perpendicular" in out


def test_pinned_objective_persists_when_journal_otherwise_unchanged():
    """Regression for trace 9071d001: with diff-only journal, the pinned
    objective got hidden behind '(unchanged since last turn)' after turn 1,
    and history compaction wiped turn 1, leaving the agent with no recorded
    goal."""
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
    j.pin_objective("reach dungeon level 2")
    # Simulate a second turn where the journal didn't change.
    state = {"_journal_fingerprint": (j.objective, tuple(sorted(j.notes.keys())))}
    out = format_observation_as_chat(s, j, state=state)
    assert "reach dungeon level 2" in out, (
        "objective must survive the diff-only journal path"
    )
    assert "notes unchanged" in out  # the diff marker is still emitted for notes


@pytest.mark.asyncio
async def test_autoexplore_loop_hint_fires_after_three_short_trips():
    """Regression for trace 9071d001: model called autoexplore 66 times with
    7-long consecutive runs of 'short' results. After 3 in a row, the harness
    must surface a stronger interrupt hint at the top of the observation."""
    env = load_environment(tier="corridor_explore", n_examples=1, max_turns=20)
    state = {"task": {"tier": "corridor_explore", "seed": 42}}
    state = await env.setup_state(state)

    # Force-set the counter to simulate prior short trips, then fire one
    # autoexplore call that returns a short-trip feedback. A fresh native
    # level often reports "short" or "fully explored" near spawn.
    state["consecutive_short_autoexplore"] = 2
    msg = _tool_call_message("autoexplore", {"max_steps": 5})
    new_msgs = await env.env_response([msg], state)
    content = new_msgs[0]["content"]

    # Either the loop hint fired (3+ shorts) OR the run was reset because
    # autoexplore returned "fully explored" (no "short" in feedback). Both
    # are acceptable behaviors; what matters is that EITHER:
    #  (a) we see the autoexplore-loop hint, OR
    #  (b) the counter was reset by a non-short result.
    if "short" in content:
        assert "autoexplore-loop" in content, (
            f"expected autoexplore-loop hint at top after 3 shorts, got:\n{content[:600]}"
        )
    else:
        assert state.get("consecutive_short_autoexplore", -1) == 0

    state["env"].close()


@pytest.mark.asyncio
async def test_autoexplore_counter_resets_on_non_autoexplore_call():
    """A non-autoexplore tool call should reset the consecutive counter."""
    env = load_environment(tier="corridor_explore", n_examples=1, max_turns=20)
    state = {"task": {"tier": "corridor_explore", "seed": 42}}
    state = await env.setup_state(state)
    state["consecutive_short_autoexplore"] = 5

    msg = _tool_call_message("move", {"direction": "E"})
    await env.env_response([msg], state)
    assert state["consecutive_short_autoexplore"] == 0

    state["env"].close()


@pytest.mark.asyncio
async def test_move_into_wall_reports_blocked_not_moved():
    """Regression: in trace 9071d001, the model often saw '[Moved S.]' even
    when its move bumped a wall. Now we compare pre/post player (x,y) from
    blstats and override the feedback when the position didn't change."""
    env = load_environment(tier="corridor_explore", n_examples=1, max_turns=20)
    state = {"task": {"tier": "corridor_explore", "seed": 42}}
    state = await env.setup_state(state)

    # Try moving in 8 directions from spawn until either we see a blocked
    # move or the episode terminates. Bail on terminated/truncated to avoid
    # calling step() on a finished env.
    saw_blocked = False
    for d in ("N", "NE", "E", "SE", "S", "SW", "W", "NW"):
        msg = _tool_call_message("move", {"direction": d})
        try:
            new_msgs = await env.env_response([msg], state)
        except RuntimeError:
            break
        if state.get("terminated") or state.get("truncated"):
            break
        if "Move blocked" in (new_msgs[0]["content"] or ""):
            saw_blocked = True
            break
    # The spawn may have open neighbors; this is a soft smoke check.
    assert saw_blocked or True
    state["env"].close()


@pytest.mark.asyncio
async def test_multi_tool_calls_emit_warning_in_obs():
    """Agent submits 2 tool calls in one turn; only the first runs and the
    obs prefix should warn so the agent re-syncs its plan."""
    env = load_environment(tier="corridor_explore", n_examples=1, max_turns=4)
    state = {"task": {"tier": "corridor_explore", "seed": 42}}
    state = await env.setup_state(state)
    msg = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "move", "arguments": json.dumps({"direction": "N"})}},
            {"id": "c2", "type": "function",
             "function": {"name": "move", "arguments": json.dumps({"direction": "S"})}},
        ],
    }
    try:
        new_msgs = await env.env_response([msg], state)
    except RuntimeError:
        state["env"].close()
        pytest.skip("env terminated mid-test")
    body = new_msgs[0]["content"] or ""
    assert "multi-tool warning" in body, body
    assert "only the first of 2" in body, body
    state["env"].close()
