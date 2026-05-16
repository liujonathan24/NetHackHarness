"""Reward-distribution sweep across scripted baseline agents.

Drives multiple deterministic policies against the real env and tabulates
per-rollout rewards. Useful as a "what does the substrate look like before
any LM training?" baseline for the Monday writeup.

Three baselines:
  random_walk:   sample a uniform direction each step
  always_search: never move; just press search/wait
  autoexplore:   one autoexplore(max_steps=200) call

For each baseline × seed, records: total_reward, scout_tiles_seen, dlvl,
hp_remaining, terminated. Outputs a summary table.

Run with:
    python experiments/baseline_agents.py --tier corridor_explore --seeds 5
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nethack_core.curriculum import get_tier
from nethack_core.env import NetHackCoreEnv
from nethack_core.observations import shape as shape_observation
from nethack_core.skills import bootstrap_character, registry

OUT_DIR = Path(__file__).parent / "results"
OUT_DIR.mkdir(exist_ok=True)


def _action_indices(env, enums):
    """Convert NLE enum values to NetHackScore action indices."""
    out = []
    for e in enums:
        ev = int(e)
        for i, a in enumerate(env.unwrapped.actions):
            if int(a) == ev:
                out.append(i)
                break
    return out


def _step_loop(core: NetHackCoreEnv, action_indices, max_actions: int) -> dict:
    """Apply up to max_actions; return rewards summary."""
    env = core.underlying
    total_r = 0.0
    n = 0
    last_obs = None
    term = trunc = False
    for a in action_indices[:max_actions]:
        last_obs, r, term, trunc, _info = env.step(a)
        total_r += float(r)
        n += 1
        if term or trunc:
            break
    return {"total_reward": total_r, "actions_taken": n, "terminated": bool(term or trunc), "last_obs": last_obs}


def random_walk(core: NetHackCoreEnv, max_steps: int, rng: random.Random) -> dict:
    n_actions = len(core.underlying.unwrapped.actions)
    # Limit to direction-like actions (indices 1-8 are compass dirs in NetHackScore)
    direction_indices = list(range(1, min(9, n_actions)))
    actions = [rng.choice(direction_indices) for _ in range(max_steps)]
    return _step_loop(core, actions, max_steps)


def always_search(core: NetHackCoreEnv, max_steps: int) -> dict:
    # Index 18 is search/wait in NetHackScore.
    return _step_loop(core, [18] * max_steps, max_steps)


def autoexplore_once(core: NetHackCoreEnv, max_steps: int, structured) -> dict:
    """Caller provides the freshly-reset structured obs (avoids juggling
    NLE's tuple-shaped last_observation cache)."""
    result = registry.call("autoexplore", core, structured, max_steps=max_steps)
    indices = _action_indices(core.underlying, result.actions)
    return _step_loop(core, indices, max_steps)


BASELINES = {
    "random_walk":  lambda core, max_s, rng, structured: random_walk(core, max_s, rng),
    "always_search": lambda core, max_s, rng, structured: always_search(core, max_s),
    "autoexplore":  lambda core, max_s, rng, structured: autoexplore_once(core, max_s, structured),
}


def run(tier: str, seeds: int, max_steps: int) -> dict:
    spec = get_tier(tier)
    rows = []
    for seed in range(seeds):
        rng = random.Random(seed)
        for name, fn in BASELINES.items():
            core = NetHackCoreEnv(task_name=spec.nle_task, des_file=spec.des_file)
            core.seed(seed, seed)
            core_obs, _ = core.reset()
            structured = shape_observation(core_obs, character={"role": "unknown"})
            r = fn(core, max_steps, rng, structured)
            rows.append({
                "baseline": name,
                "seed": seed,
                "total_reward": round(r["total_reward"], 3),
                "actions_taken": r["actions_taken"],
                "terminated": r["terminated"],
            })
            core.close()

    summary: dict = {"tier": tier, "max_steps": max_steps, "rows": rows}
    by_baseline: dict[str, list[float]] = {b: [] for b in BASELINES}
    for r in rows:
        by_baseline[r["baseline"]].append(r["total_reward"])
    summary["by_baseline_stats"] = {
        b: {
            "mean": round(statistics.mean(vs), 3),
            "stdev": round(statistics.stdev(vs), 3) if len(vs) > 1 else 0.0,
            "max": round(max(vs), 3),
            "min": round(min(vs), 3),
            "n": len(vs),
        }
        for b, vs in by_baseline.items()
    }

    summary["verdict"] = "BASELINE"  # not a regression test; just descriptive
    out_path = OUT_DIR / f"baseline_agents_{tier}.json"
    out_path.write_text(json.dumps(summary, indent=2))
    return summary


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tier", default="corridor_explore")
    p.add_argument("--seeds", type=int, default=5)
    p.add_argument("--max-steps", type=int, default=200)
    args = p.parse_args()

    summary = run(args.tier, args.seeds, args.max_steps)
    print(f"\nBaseline reward distribution (tier={args.tier}, seeds={args.seeds}, max_steps={args.max_steps})")
    print(f"{'baseline':<18} {'mean':>8} {'stdev':>8} {'min':>8} {'max':>8}  n")
    print("-" * 64)
    for b, s in summary["by_baseline_stats"].items():
        print(f"{b:<18} {s['mean']:>8} {s['stdev']:>8} {s['min']:>8} {s['max']:>8}  {s['n']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
