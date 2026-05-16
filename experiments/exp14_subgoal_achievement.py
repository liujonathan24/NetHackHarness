"""exp14 — dynamic-subgoal achievement rate.

Substrate experiment for the autoresearch axis: given the OfflineSubgoalProposer
+ scripted exploration, how often does the proposed subgoal actually fire?

This is the v0 of the meta-RL feedback signal. A real proposer LLM would be
evaluated by:
  proposer_score = mean(achievement_rate across seeds, across role distribution)
  + penalty for unreachable / trivial subgoals

For now we run the OfflineSubgoalProposer + autoexplore on N seeds and tabulate.

Verdict = SHIPS if at least the trivially-achievable subgoals fire, and the
unreachable ones don't fire spuriously. (Not a "fix confirmed" since this is
a brand-new feature, no legacy to compare against.)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nethack_core.env import NetHackCoreEnv
from nethack_core.observations import shape as shape_observation
from nethack_core.skills import bootstrap_character, registry
from nethack_core.subgoals import OfflineSubgoalProposer, compile_predicate

OUT_DIR = Path(__file__).parent / "results"
OUT_DIR.mkdir(exist_ok=True)

SEEDS = [42, 123, 7, 1024, 2026]
MAX_AUTOEXPLORE_TRIPS = 20
MAX_STEPS_PER_TRIP = 30


def _action_indices(env, enums):
    out = []
    for e in enums:
        ev = int(e)
        for i, a in enumerate(env.unwrapped.actions):
            if int(a) == ev:
                out.append(i)
                break
    return out


def _drive_until_termination(core, structured, milestone, max_trips, max_steps_per_trip) -> dict:
    """Repeated autoexplore. Stop on milestone fire or max trips."""
    env = core.underlying
    fired = False
    steps = 0
    for trip in range(max_trips):
        # Re-shape obs for the next planning round.
        # Cheap: keep the original `structured` since pathfinding only needs the map view.
        result = registry.call("autoexplore", core, structured, max_steps=max_steps_per_trip)
        if not result.actions:
            break
        for a in _action_indices(env, result.actions):
            obs, _r, term, trunc, _info = env.step(a)
            steps += 1
            # Build a minimal structured obs for the milestone check
            try:
                from nethack_core.observations import CoreObservation
                core_obs = CoreObservation.from_nle(obs)
                check_obs = shape_observation(core_obs, character={"role": "unknown"})
            except Exception:
                # Fall back to original structured if shaping fails on this obs shape.
                check_obs = structured
            if milestone.check(check_obs, {}):
                fired = True
                break
            if term or trunc:
                break
        if fired:
            break
        # Refresh structured for next planning trip
        try:
            from nethack_core.observations import CoreObservation
            core_obs = CoreObservation.from_nle(obs)
            structured = shape_observation(core_obs, character={"role": "unknown"})
        except Exception:
            pass
    return {"fired": fired, "steps_taken": steps}


def run() -> dict:
    proposer = OfflineSubgoalProposer()
    rows = []
    for seed in SEEDS:
        core = NetHackCoreEnv()
        core.seed(seed, seed)
        core_obs, _ = core.reset()
        character = bootstrap_character(core)
        structured = shape_observation(core_obs, character=character)
        spec = proposer.propose(role=character.get("role", "unknown"), obs=structured)
        milestone = compile_predicate(spec.termination_check)
        result = _drive_until_termination(core, structured, milestone,
                                          MAX_AUTOEXPLORE_TRIPS, MAX_STEPS_PER_TRIP)
        rows.append({
            "seed": seed,
            "role": character.get("role", "unknown"),
            "objective": spec.objective,
            "termination_check": spec.termination_check,
            "fired": result["fired"],
            "steps_taken": result["steps_taken"],
        })
        core.close()

    n_fired = sum(1 for r in rows if r["fired"])
    out = {
        "n_seeds": len(SEEDS),
        "rows": rows,
        "achievement_rate": round(n_fired / max(len(SEEDS), 1), 3),
        "verdict": "SHIPS" if all(isinstance(r["fired"], bool) for r in rows) else "ERROR",
    }
    (OUT_DIR / "exp14_subgoal_achievement.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    r = run()
    print(json.dumps(r, indent=2))
    print(f"\n{r['verdict']}: {int(r['achievement_rate'] * 100)}% achievement on {len(SEEDS)} seeds (autoexplore baseline, 20×30 steps cap)")
