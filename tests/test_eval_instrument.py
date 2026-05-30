"""Unit tests for tools/eval_instrument.py — Wilson CI + failure taxonomy.

The starvation-vs-stuck distinction is the load-bearing case: both end
with the agent not moving, but starvation has a clear textual signal,
while stuck_no_progress is detected from the trace's scout_delta tail.
"""
from __future__ import annotations

import math

import pytest

from tools.eval_instrument import (
    classify_failure,
    summarize_eval,
    wilson_ci,
)


# ---------------------------------------------------------------------------
# Wilson CI
# ---------------------------------------------------------------------------

def test_wilson_ci_known_values():
    # Known reference: k=2, n=10 → Wilson 95% ≈ [0.057, 0.510]
    lo, hi = wilson_ci(2, 10)
    assert math.isclose(lo, 0.0567, abs_tol=2e-3), lo
    assert math.isclose(hi, 0.5101, abs_tol=2e-3), hi

def test_wilson_ci_edges():
    assert wilson_ci(0, 0) == (0.0, 0.0)
    lo, hi = wilson_ci(0, 5)
    assert lo == 0.0 and hi > 0
    lo, hi = wilson_ci(5, 5)
    assert hi == 1.0 and lo < 1


# ---------------------------------------------------------------------------
# Failure taxonomy
# ---------------------------------------------------------------------------

def _rollout(user_msgs, *, info=None, trace=None,
             scout_reward=0.0, descent_reward=0.0) -> dict:
    return {
        "completion": [{"role": "user", "content": m} for m in user_msgs],
        "info": info or {"is_completed": True, "is_truncated": False},
        "trace": trace,
        "scout_reward": scout_reward,
        "descent_reward": descent_reward,
        "reward": scout_reward + descent_reward,
    }


def test_starved_vs_stuck_no_progress():
    """A starvation death and a stuck rollout look superficially similar
    (both end with little movement) — the classifier MUST distinguish them
    by the 'starved' text signal, not by the scout-delta tail.
    """
    starved = _rollout(
        ["You feel weak.", "You faint from lack of food.",
         "You died of starvation."],
        info={"is_completed": True, "is_truncated": False},
    )
    assert classify_failure(starved) == "starved"

    # Stuck: no death banner, trace shows zero scout-delta over the tail
    stuck = _rollout(
        ["=== MAP === room", "[Autoexplore: short]", "[Autoexplore: short]"],
        info={"is_completed": False, "is_truncated": True},
        trace=[{"scout_delta": 0.0} for _ in range(60)],
    )
    # is_truncated is true, but the more-specific stuck signal? Per the
    # cascade, turn_budget wins over stuck because is_truncated fires
    # first. That's the documented contract — verify it.
    assert classify_failure(stuck) == "turn_budget"

    # Pure stuck (not truncated): scout-delta sum is 0
    pure_stuck = _rollout(
        ["=== MAP ===", "[move blocked]", "[move blocked]"],
        info={"is_completed": False, "is_truncated": False},
        trace=[{"scout_delta": 0.0} for _ in range(60)],
    )
    assert classify_failure(pure_stuck) == "stuck_no_progress"


def test_killed_and_door_block():
    killed = _rollout(
        ["The kobold hits!",
         "You die...",
         "Killed by a kobold, while helpless."],
    )
    assert classify_failure(killed) == "killed_by_monster"

    door = _rollout(
        ["=== MAP === a door at (5,5)",
         "You see a door here.",
         "You see a closed door."],
        info={"is_completed": False, "is_truncated": False},
    )
    assert classify_failure(door) == "door_block"


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def test_summarize_eval_descent_rate_and_ci():
    samples = [
        # 2 descended, 3 did not (1 starved, 1 killed, 1 other)
        _rollout(["ok"], descent_reward=1.0, scout_reward=0.2),
        _rollout(["ok"], descent_reward=2.0, scout_reward=0.3),
        _rollout(["You died of starvation."]),
        _rollout(["Killed by a sewer rat."]),
        _rollout(["nothing notable"]),
    ]
    s = summarize_eval(samples)
    assert s["n"] == 5
    assert s["k_descended"] == 2
    assert math.isclose(s["descent_rate"], 0.4)
    assert s["failure_taxonomy"]["starved"] == 1
    assert s["failure_taxonomy"]["killed_by_monster"] == 1
    assert s["failure_taxonomy"]["other"] == 1
    # Per-seed bookkeeping
    assert sum(1 for r in s["per_seed"] if r["descended"]) == 2
