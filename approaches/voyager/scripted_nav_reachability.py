"""Deterministic (no-LLM) navigation-ceiling sweep on the compressed tour.

The LLM sweep showed climbing is gated by whether the navigator can reach the
up-stair on a given level — a HARNESS property, not an agent-reasoning property.
This script measures that property directly and FOR FREE (no API): a scripted
climber that, from a constructed start floor, just repeatedly paths to the nearest
up-stair (via the door-aware nav_to) and takes it, attacking an adjacent monster
if one blocks the way and searching when no up-stair is visible. It reports how
far it climbs from each start floor across many seeds.

This is the *navigation ceiling*: the best a legal-primitives agent could do if its
reasoning were perfect — the upper bound the LLM agent is working against. Because
it uses no API, it covers every floor x seed the Prime/Gemini budgets could not.

    python scripted_nav_reachability.py --seeds-range 40 --out outputs/.../scripted
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import numpy as np

_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "environments" / "nethack"))
sys.path.insert(0, str(_ROOT / "approaches" / "voyager"))

import curriculum_voyager as cv  # noqa: E402
import reverse_curriculum_sweep as rc  # noqa: E402
from nethack_core.curriculum_engine_env import CurriculumEngineEnv  # noqa: E402


def _nearest(pts, hero):
    return min(pts, key=lambda p: abs(p[0] - hero[0]) + abs(p[1] - hero[1]))


def _attack_adjacent_monster(env, obs):
    """If a monster is orth/diagonally adjacent, step into it (attack). Returns
    (obs, done, acted)."""
    chars = np.array(obs.chars).reshape(21, 79)
    cx, cy = cv._pos(obs)
    for key, (dx, dy) in cv._DIRS.items():
        x, y = cx + dx, cy + dy
        if 0 <= x < 79 and 0 <= y < 21 and cv._is_monster(chr(int(chars[y, x]))) \
                and chr(int(chars[y, x])) != "@":
            o, done, _ = env.step(key)
            return o, done, True
    return obs, False, False


def scripted_climb(env, obs, start_floor: int, max_iters: int = 80) -> dict:
    floors = [env.curriculum_floor(obs)]
    f_cur = floors[0]
    stuck = 0
    reached_top = (f_cur == 1)
    for _ in range(max_iters):
        if env.curriculum_floor(obs) == 1:
            reached_top = True
            break
        on = env._engine.hero_on_stair()
        if on == -1:
            obs, done, _ = cv._exec(env, {"tool": "stairs_up"})
        else:
            chars = np.array(obs.chars).reshape(21, 79)
            _downs, ups = cv._stairs(chars)
            if ups:
                obs, done, msg = rc.nav_to(env, *_nearest(ups, cv._pos(obs)))
                if env._engine.hero_on_stair() == -1:
                    obs, done, _ = cv._exec(env, {"tool": "stairs_up"})
                elif "monster" in msg:
                    obs, done, acted = _attack_adjacent_monster(env, obs)
                else:
                    stuck += 1
            else:                              # no up-stair visible: search
                for _ in range(8):
                    obs, done, _ = env.step(ord("s"))
                stuck += 1
        nf = env.curriculum_floor(obs)
        if nf > 0 and nf < f_cur:              # climbed a floor -> progress
            stuck = 0
            f_cur = nf
        floors.append(nf)
        if stuck >= 5:
            break
    min_floor = min(f for f in floors if f > 0)
    return {
        "start_floor": start_floor,
        "reached_top": bool(reached_top or min_floor == 1),
        "floors_climbed": int(start_floor - min_floor),
        "stuck_floor": int(min_floor) if min_floor > 1 else None,
        "iters": len(floors) - 1,
        "floor_path": floors,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds-range", type=int, default=40,
                    help="test seeds 0..N-1 that have a full 6-floor deep segment")
    ap.add_argument("--seeds", type=int, nargs="+", default=None)
    ap.add_argument("--out", default="outputs/curriculum_experiments/scripted_nav")
    args = ap.parse_args()
    out = pathlib.Path(args.out); (out / "episodes").mkdir(parents=True, exist_ok=True)

    # choose seeds with a full deep segment (floors 4..6 well-defined)
    if args.seeds:
        seeds = args.seeds
    else:
        seeds = []
        for s in range(args.seeds_range):
            env = CurriculumEngineEnv(); env.reset(seeds=(s, s))
            if env._deep_lo == 48 and env._deep_hi >= 50:
                seeds.append(s)
    print(f"[scripted] {len(seeds)} full-depth seeds: {seeds}")

    results = []
    for s in seeds:
        for floor in (2, 3, 4, 5, 6):
            env = CurriculumEngineEnv(); obs, _ = env.reset(seeds=(s, s))
            try:
                dnum, dl = rc._floor_to_abs(env, floor)
                env.goto_abs(dnum, dl); obs = env.modify(**env._sample_upgrade())
            except ValueError:
                continue
            r = scripted_climb(env, obs, floor)
            r.update({"seed": s, "condition": f"climb_from_{floor}"})
            results.append(r)
            print(f"  seed{s:2d} climb_from_{floor}: top={r['reached_top']} "
                  f"climbed={r['floors_climbed']} stuck@{r['stuck_floor']} "
                  f"iters={r['iters']}", flush=True)

    (out / "results.json").write_text(json.dumps(results, indent=2))

    # aggregate per start floor
    print("\n=== navigation ceiling (scripted, no LLM) ===")
    print("| start floor | n seeds | P(reach top) | mean climbed | median stuck floor |")
    print("|---|---|---|---|---|")
    agg = {}
    for floor in (2, 3, 4, 5, 6):
        lst = [r for r in results if r["start_floor"] == floor]
        if not lst:
            continue
        top = np.mean([r["reached_top"] for r in lst])
        climbed = np.mean([r["floors_climbed"] for r in lst])
        stucks = [r["stuck_floor"] for r in lst if r["stuck_floor"]]
        agg[floor] = {"n": len(lst), "p_top": round(float(top), 3),
                      "mean_climbed": round(float(climbed), 2),
                      "median_stuck": int(np.median(stucks)) if stucks else None}
        print(f"| {floor} | {len(lst)} | {agg[floor]['p_top']} | "
              f"{agg[floor]['mean_climbed']} | {agg[floor]['median_stuck']} |")
    (out / "summary.json").write_text(json.dumps(agg, indent=2))
    print(f"\nwrote {out}/results.json + summary.json")


if __name__ == "__main__":
    main()
