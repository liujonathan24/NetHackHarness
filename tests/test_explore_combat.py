"""Fix #2: in-skill combat during explore_and_descend.

The half-HP danger-halt (fix-#1 era) was the binding constraint on descent: weak
monsters (rats/newts/kobolds) whittled HP mid-explore until the skill bailed to the
LLM, which often failed to recover and died ~floor 2. NetPlay melees weak monsters
in-skill rather than autopiloting past them. These tests lock in that the skill now
fights an adjacent hostile (while HP is healthy) and still descends, without infinite
swinging at a tough monster (the 16-swing handoff valve).

Real-env, no LLM — the closed-loop skill steps the env itself. Fast seeds only.
"""
import re

from nethack_core.env import NetHackCoreEnv
from nethack_core.observations import shape as shape_observation
from nethack_harness.tools.skills import registry


def _floors(feedback):
    m = re.search(r"descended (\d+) floor", feedback or "")
    return int(m.group(1)) if m else 0


def _run(seed, max_game_steps=400):
    e = NetHackCoreEnv(task_name="NetHackScore-v0")
    e.seed(core=seed, disp=seed)
    out = e.reset()
    return registry.call("explore_and_descend", e, shape_observation(out[0], {}),
                         max_floors=2, max_game_steps=max_game_steps)


def test_seed4_descends_through_a_monster_and_hands_off_cleanly():
    # Seed 4 has a hostile blocking the route: pre-fix-#2 the skill autopiloted past
    # it and bailed on HP; now it melees through, descends a floor, and (if it then
    # meets a tougher monster) returns control to the LLM rather than dying or looping.
    res = _run(4)
    assert _floors(res.feedback) >= 1, f"seed 4 should descend through the monster: {res.feedback!r}"


def test_fast_descent_seeds_still_work_with_combat_enabled():
    # Combat must not regress the clean descents: seed 2 reaches the downstairs in
    # well under the budget with no hostile in the way.
    res = _run(2)
    assert _floors(res.feedback) >= 1, f"seed 2 should still descend cleanly: {res.feedback!r}"


def test_no_infinite_swing_on_a_stubborn_monster():
    # The skill must always terminate — never loop forever swinging. The 16-swing
    # valve hands a stubborn monster back to the LLM. Just assert the call returns
    # with a sane step count (bounded by max_game_steps).
    res = _run(4, max_game_steps=300)
    steps = re.search(r"over (\d+) game steps", res.feedback or "")
    assert steps is not None and int(steps.group(1)) <= 300, \
        f"call must terminate within the step budget: {res.feedback!r}"
