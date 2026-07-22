"""LLM-guided Go-Explore on the compressed curriculum.

Go-Explore's archive (snapshot cells, return to promising ones) combined with an
LLM exploration policy instead of random actions: from a restored cell the LLM
(GLM via Prime Inference, full vision) chooses real moves / navigation / real
stairs to push deeper (and, once bottomed, back up). Same faithful constraints as
the other curriculum runners — NO descend/ascend skill; the 3<->48 jump is
internal, fired only on genuine stair use.

Measures the deepest curriculum floor reached AND floors climbed back, over
Go-Explore iterations. Needs PI_API_KEY (the Prime api_key).

Run::

    PI_API_KEY=... python approaches/go_explore/curriculum_go_explore_llm.py \
        --iterations 30 --explore-turns 8 --seeds 19 2 9 \
        --out outputs/curriculum_experiments/go_explore_llm
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import sys
from dataclasses import dataclass

_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "environments" / "nethack"))
sys.path.insert(0, str(_ROOT / "approaches" / "voyager"))

from nethack_core import CurriculumEngineEnv  # noqa: E402
# Reuse the faithful LLM action helpers (move_to via A*, real stairs, render).
import curriculum_voyager as V  # noqa: E402

MAX_FLOOR = 6
_GRID = 3


@dataclass
class Cell:
    handle: object
    progress: int
    max_floor: int
    n_visits: int = 0


def _progress(floor, bottomed):
    if floor <= 0:
        return 0
    return floor if not bottomed else MAX_FLOOR + (MAX_FLOOR - floor)


def _key(obs, prog):
    x, y = int(obs.blstats[0]), int(obs.blstats[1])
    return (prog, int(obs.blstats[23]), x // _GRID, y // _GRID)


def run(*, iterations, explore_turns, seed, model, api_key, verbose=True):
    env = CurriculumEngineEnv()
    obs, _ = env.reset(seeds=(seed, seed))
    f0 = env.curriculum_floor(obs)
    archive = {_key(obs, _progress(f0, False)): Cell(env.snapshot(), _progress(f0, False), f0)}
    deepest, min_after_bottom, bottomed_ever = f0, MAX_FLOOR, False
    timeseries = []
    rng = random.Random(seed)
    last_fb = "Begin."

    for it in range(iterations):
        # SELECT a cell, weighted toward higher tour progress / fewer visits.
        keys = list(archive)
        weights = [(1.0 + archive[k].progress) / (1.0 + archive[k].n_visits) for k in keys]
        key = rng.choices(keys, weights=weights, k=1)[0]
        cell = archive[key]
        cell.n_visits += 1
        env.restore(cell.handle)
        env.engine.reseed(core=10_000 + it, disp=20_000 + it)
        running_max = cell.max_floor

        # EXPLORE with the LLM for a few turns.
        for _ in range(explore_turns):
            obs = env._engine.to_core_observation()
            view, _pos, _d, _u = V._render(env, obs)
            user = f"{view}\n\nLast: {last_fb}\nNext tool call (push deeper, then climb back up):"
            try:
                content = V._glm(model, [{"role": "system", "content": V.SYSTEM},
                                         {"role": "user", "content": user}], api_key)
            except Exception as exc:
                last_fb = f"(LLM error: {exc})"
                break
            action = V._parse(content)
            try:
                obs, done, last_fb = V._exec(env, action)
            except Exception as exc:
                done, last_fb = False, f"(tool error: {exc})"
            floor = env.curriculum_floor(obs)
            if floor > 0:
                running_max = max(running_max, floor)
            bottomed = running_max >= MAX_FLOOR
            prog = _progress(floor, bottomed)
            nk = _key(obs, prog)
            ex = archive.get(nk)
            if ex is None or prog > ex.progress:
                h = env.snapshot()
                if ex is not None:
                    try:
                        env.free_snapshot(ex.handle)
                    except Exception:
                        pass
                archive[nk] = Cell(h, prog, running_max, ex.n_visits if ex else 0)
            if floor > 0:
                deepest = max(deepest, floor)
            if bottomed:
                bottomed_ever = True
                if floor > 0:
                    min_after_bottom = min(min_after_bottom, floor)
            if done:
                break

        climbed = (deepest - min_after_bottom) if bottomed_ever else 0
        timeseries.append({"iter": it + 1, "deepest_floor": deepest,
                           "climbed_back": climbed, "cells": len(archive)})
        if verbose:
            print(f"[iter {it+1:3d}] cells={len(archive)} deepest={deepest}/6 climbed_back={climbed}", flush=True)

    return {"algo": "go_explore_llm", "seed": seed, "model": model,
            "deepest_floor": deepest,
            "climbed_back": (deepest - min_after_bottom) if bottomed_ever else 0,
            "reached_bottom": bottomed_ever, "iterations": iterations,
            "n_cells": len(archive), "timeseries": timeseries}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=30)
    ap.add_argument("--explore-turns", type=int, default=8)
    ap.add_argument("--seeds", type=int, nargs="+", default=[19])
    ap.add_argument("--model", default="z-ai/glm-5.2")
    ap.add_argument("--out", default="outputs/curriculum_experiments/go_explore_llm")
    args = ap.parse_args()
    api_key = os.environ.get("PI_API_KEY") or os.environ.get("REFINER_API_KEY")
    if not api_key:
        raise SystemExit("set PI_API_KEY (the Prime api_key)")
    out = pathlib.Path(args.out); out.mkdir(parents=True, exist_ok=True)
    summary = []
    for seed in args.seeds:
        print(f"=== LLM Go-Explore curriculum: seed {seed} ({args.model}) ===")
        res = run(iterations=args.iterations, explore_turns=args.explore_turns,
                  seed=seed, model=args.model, api_key=api_key)
        (out / f"go_explore_llm_seed{seed}.json").write_text(json.dumps(res, indent=2))
        summary.append({k: res[k] for k in
                        ("seed", "deepest_floor", "climbed_back", "reached_bottom")})
        print(f"  -> deepest_floor={res['deepest_floor']}/6 climbed_back={res['climbed_back']}")
    (out / "go_explore_llm_summary.json").write_text(json.dumps(summary, indent=2))
    print("summary:", json.dumps(summary))


if __name__ == "__main__":
    main()
