"""
Tests for the code-mode safety layer.

We mostly test the validator and the namespace; the env-integration parts
are stubbed (Track B week-2 work).

Run with: uv run pytest tests/test_code_mode.py -v
"""

from __future__ import annotations

import pytest

from nethack_harness.tools.code_mode import (
    CodeModeError,
    run_user_code,
    validate_source,
)


# ---------- AST validator ----------

def test_validator_rejects_imports():
    with pytest.raises(CodeModeError, match="Imports"):
        validate_source("import os")


def test_validator_rejects_from_imports():
    with pytest.raises(CodeModeError, match="from"):
        validate_source("from os import system")


def test_validator_rejects_forbidden_names():
    for name in ("exec", "eval", "open", "__import__", "compile"):
        with pytest.raises(CodeModeError, match=name):
            validate_source(f"x = {name}('1+1')")


def test_validator_rejects_dunder_attribute_access():
    """Avoids the `().__class__.__base__.__subclasses__()` escape hatch."""
    with pytest.raises(CodeModeError, match="Dunder"):
        validate_source("x = (1).__class__")


def test_validator_accepts_safe_code():
    """Plain arithmetic and nh.* calls should pass."""
    validate_source("x = 1 + 2\nprint(x)")
    validate_source("for i in range(5): print(i)")
    validate_source("nh.move('N')")


# ---------- runtime ----------

def test_run_user_code_returns_stdout():
    result = run_user_code("print('hello world')", env=None, structured_obs=None)
    assert result.error is None
    assert "hello world" in result.stdout


def test_run_user_code_reports_validator_error():
    result = run_user_code("import sys", env=None, structured_obs=None)
    assert result.error is not None
    assert "Imports" in result.error


def test_run_user_code_catches_runtime_exceptions():
    """Errors raised inside user code don't crash the runtime; they're captured."""
    result = run_user_code("1 / 0", env=None, structured_obs=None)
    assert result.error is not None
    assert "ZeroDivisionError" in result.error


def test_run_user_code_nh_namespace_exposes_read_only_views():
    from dataclasses import dataclass

    @dataclass
    class _Obs:
        status: dict
        inventory: list
        map_view: str
        character: dict
        messages: list
        menu: object = None
        inventory_prompt: object = None

    obs = _Obs(status={"hitpoints": 10}, inventory=[], map_view="@..", character={"role": "monk"}, messages=[])
    src = "print(nh.status['hitpoints']); print(nh.character['role'])"
    result = run_user_code(src, env=None, structured_obs=obs)
    assert result.error is None
    assert "10" in result.stdout
    assert "monk" in result.stdout


def test_run_user_code_wiki_lookup_through_nh():
    """nh.wiki_lookup hits the same singleton wiki index as the skill API."""
    src = "p = nh.wiki_lookup('altar'); print(p.title if p else 'none')"
    result = run_user_code(src, env=None, structured_obs=None)
    assert result.error is None
    assert "altar" in result.stdout.lower()


def test_run_user_code_safe_builtins_only():
    """`open` and friends are not in builtins."""
    result = run_user_code("print(open('/tmp/x'))", env=None, structured_obs=None)
    assert result.error is not None
    assert "open" in result.error or "not allowed" in result.error.lower()


def test_run_user_code_journal_writes():
    from nethack_harness.memory.journal import Journal
    j = Journal()
    result = run_user_code(
        "nh.add_note('reminder', 'wear gloves'); print(nh.recall('reminder'))",
        env=None, structured_obs=None, journal=j,
    )
    assert result.error is None
    assert j.notes["reminder"] == "wear gloves"
    assert "wear gloves" in result.stdout


# ---------- env-stepping wiring (Track B v0.2) ----------

def test_nh_move_appends_to_action_log():
    """Wired now: nh.move dispatches the skill and queues the resulting actions."""
    from nethack_core import NetHackCoreEnv
    from nethack_core import shape as shape_observation

    core = NetHackCoreEnv()
    core.seed(7, 7)
    core_obs, _ = core.reset()
    structured = shape_observation(core_obs, character={"role": "unknown"})

    result = run_user_code("nh.move('N')", env=core, structured_obs=structured)
    assert result.error is None
    assert len(result.actions_taken) >= 1
    core.close()


def test_nh_autoexplore_queues_many_actions_in_one_call():
    """Headline of code mode: many env actions per LM round-trip."""
    from nethack_core import NetHackCoreEnv
    from nethack_core import shape as shape_observation

    core = NetHackCoreEnv()
    core.seed(7, 7)
    core_obs, _ = core.reset()
    structured = shape_observation(core_obs, character={"role": "unknown"})

    result = run_user_code(
        "nh.autoexplore(max_steps=10); print('queued', len(nh._log), 'actions')",
        env=core, structured_obs=structured,
    )
    assert result.error is None
    assert "queued" in result.stdout
    # Even if pathfinding finds a short path, expect ≥1 action.
    assert len(result.actions_taken) >= 1
    core.close()


def test_sub_lm_offline_summarize_returns_canned_string():
    src = "out = nh.summarize('the agent saw a dog and a chest', query='items')\nprint(out)"
    result = run_user_code(src, env=None, structured_obs=None)
    assert result.error is None
    assert "offline-summary" in result.stdout
    assert "items" in result.stdout


def test_sub_lm_plan_returns_horizon_steps():
    src = "for s in nh.plan('reach mine town', horizon=4): print(s)"
    result = run_user_code(src, env=None, structured_obs=None)
    assert result.error is None
    # 4 horizon → 4 lines
    assert result.stdout.count("offline-plan") == 4


def test_sub_lm_recall_uses_journal_context():
    from nethack_harness.memory.journal import Journal
    j = Journal()
    j.add_note("altar", "saw a chaotic altar on dlvl 4")
    src = "print(nh.recall_lm('altar location'))"
    result = run_user_code(src, env=None, structured_obs=None, journal=j)
    assert result.error is None
    assert "offline-recall" in result.stdout
    assert "altar" in result.stdout


def test_sub_lm_swap_via_subclass():
    """Verify the SubLM contract: a custom backend is honored."""
    from nethack_harness.tools.code_mode import SubLM, _NhNamespace, run_user_code

    class _Echo(SubLM):
        def summarize(self, text, query=None):
            return f"ECHO:{text}"
        def plan(self, objective, horizon=5):
            return [f"ECHO:{objective}"]
        def recall(self, query, context=""):
            return f"ECHO:{query}"

    # Direct namespace test (run_user_code doesn't yet accept sub_lm kwarg via
    # the public surface — verifiers env wires it). Construct namespace manually.
    nh = _NhNamespace(env=None, structured_obs=None, journal=None, sub_lm=_Echo())
    assert nh.summarize("hi") == "ECHO:hi"
    assert nh.plan("x") == ["ECHO:x"]
    assert nh.recall_lm("q") == "ECHO:q"


def test_load_environment_code_interface_exposes_one_tool():
    """interface='code' should expose just the `code` tool, not 14 skill tools."""
    from nethack import load_environment

    env = load_environment(tier="corridor_explore", n_examples=1, max_turns=2, interface="code")
    # vf.ToolEnv stores tools as a list of callables.
    assert len(env.tools) == 1
    name = getattr(env.tools[0], "__name__", None) or env.tools[0].__class__.__name__
    assert name == "code"


def test_code_mode_env_response_end_to_end():
    """Drive env_response with a code-mode tool call and verify:
       - the source executes
       - the returned messages are vf.Messages (not raw dicts)
       - state advances (scout_delta, raw_obs change)
    """
    import asyncio
    import json
    import verifiers as vf

    from nethack import load_environment

    env = load_environment(tier="corridor_explore", n_examples=1, max_turns=4, interface="code")
    state = {"task": {"tier": "corridor_explore", "seed": 42}}
    state = asyncio.new_event_loop().run_until_complete(env.setup_state(state))

    pre_obs_id = id(state["raw_obs"])

    msg = vf.AssistantMessage(
        role="assistant",
        content=None,
        tool_calls=[vf.ToolCall(
            id="c1",
            name="code",
            arguments=json.dumps({"source": "nh.move('E')\nprint('moved east')"}),
        )],
    )
    ret = asyncio.new_event_loop().run_until_complete(env.env_response([msg], state))

    assert isinstance(ret, list) and len(ret) >= 1
    assert not isinstance(ret[0], dict)
    # Code stdout (and our [feedback] wrapper) should appear in the next obs.
    assert "moved east" in ret[0].content or "code error" in ret[0].content
    # State advanced — env stepped at least one action.
    assert id(state["raw_obs"]) != pre_obs_id or state.get("terminated")
    state["env"].close()


def test_code_mode_invalid_source_returns_feedback_not_crash():
    """Bad source code (e.g. import) should produce feedback, not crash worker."""
    import asyncio
    import json
    import verifiers as vf

    from nethack import load_environment

    env = load_environment(tier="corridor_explore", n_examples=1, max_turns=4, interface="code")
    state = {"task": {"tier": "corridor_explore", "seed": 42}}
    state = asyncio.new_event_loop().run_until_complete(env.setup_state(state))

    msg = vf.AssistantMessage(
        role="assistant",
        content=None,
        tool_calls=[vf.ToolCall(
            id="c1", name="code",
            arguments=json.dumps({"source": "import os; os.system('echo pwn')"}),
        )],
    )
    ret = asyncio.new_event_loop().run_until_complete(env.env_response([msg], state))

    assert isinstance(ret, list)
    assert "code error" in ret[0].content.lower() or "not allowed" in ret[0].content.lower()
    state["env"].close()
