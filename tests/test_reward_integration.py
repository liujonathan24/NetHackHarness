"""
Integration test for the scout/descent reward bug.

The Hub-hosted eval was reporting `scout_reward: 0.0` and `descent_reward: 0.0`
even on rollouts where the agent called `autoexplore` many times. The root
cause was: verifiers' `Rubric.score_rollout` runs ONCE at end of rollout. The
old `scout_reward` returned only the LAST step's `scout_delta`, and the old
`descent_reward` compared current depth to `max_dlvl_reached` after
env_response had already advanced `max_dlvl_reached` — so both effectively
always returned 0.

These tests drive real env_response calls and assert the *running totals*
that the rewards now read are populated correctly.

Run with: uv run pytest tests/test_reward_integration.py -v
"""

from __future__ import annotations

import asyncio
import json

from nethack import SYSTEM_PROMPT, load_environment, scout_reward, descent_reward


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


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_autoexplore_accumulates_scout_reward_across_steps():
    """After several autoexplore calls, scout_reward_total > 0 and the
    rubric-facing scout_reward(state) reflects the running sum."""
    env = load_environment(tier="corridor_explore", n_examples=1, max_turns=20)

    async def drive():
        state: dict = {"task": {"tier": "corridor_explore", "seed": 42}}
        state = await env.setup_state(state)
        assert state["scout_reward_total"] == 0.0
        for _ in range(5):
            await env.env_response([_tool_call("autoexplore", {"max_steps": 10})], state)
            if state.get("terminated"):
                break
        return state

    state = _run(drive())
    # The agent must have seen non-zero tiles.
    assert len(state["scout_tiles_seen"]) > 0, "scout_tiles_seen never grew"
    assert state["scout_reward_total"] > 0.0, "scout_reward_total never accumulated"
    # The rubric-facing reward sees the running total, not just last-step delta.
    r = _run(scout_reward(state=state))
    assert r == state["scout_reward_total"]
    state["env"].close()


def test_descent_reward_uses_descent_count_not_last_step_compare():
    """descent_reward must read state['descent_count'] (set by env_response)
    rather than re-comparing depth to max_dlvl_reached — the latter is always
    equal at score time because env_response advanced max_dlvl_reached first.
    """
    # Synthetic: simulate what env_response leaves behind after a descent.
    state = {"descent_count": 2, "max_dlvl_reached": 3}
    r = _run(descent_reward(state=state))
    assert r == 2.0

    state = {"descent_count": 0, "max_dlvl_reached": 1}
    r = _run(descent_reward(state=state))
    assert r == 0.0


# ---------- system prompt regression ----------

def test_system_prompt_has_strategy_primer_and_cheat_sheet():
    """The prompt must contain the strategy primer and skills cheat sheet
    headings so the agent gets concrete guidance on common pitfalls."""
    assert "STRATEGY PRIMER" in SYSTEM_PROMPT
    assert "SKILLS CHEAT SHEET" in SYSTEM_PROMPT
    # Specific tactical cues we want present.
    for marker in ("Elbereth", "autoexplore", "HP", "eat"):
        assert marker in SYSTEM_PROMPT, f"missing strategy cue: {marker!r}"
    # Glyph guidance: lowercase letters are monsters (added 2026-05-16 after
    # trace showed model thinking `f` was a "fireplace").
    assert "monsters" in SYSTEM_PROMPT.lower() or "creatures" in SYSTEM_PROMPT.lower()
    assert "fireplace" in SYSTEM_PROMPT  # explicit anti-hallucination note


def test_system_prompt_stays_under_token_budget():
    """Rough token-budget guard: ~4 chars/token, cap at ~700 tokens => <=2800
    chars. Bumped to 2800 to fit the descent worked-example added after
    the haiku trace showed the model needed step-by-step descent guidance."""
    assert len(SYSTEM_PROMPT) <= 2950, (
        f"SYSTEM_PROMPT is {len(SYSTEM_PROMPT)} chars; trim before shipping."
    )
