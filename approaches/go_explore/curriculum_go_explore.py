"""Go-Explore on the compressed curriculum, measuring how deep the agent
descends AND how far it climbs back up over time — using ONLY real game
primitives (compass moves, search, and the real stair commands `>` / `<`).

There is no descend/ascend skill. The agent must navigate onto the real stairs
and press `>` / `<`; the curriculum env redirects only at the 3<->48 boundary
(internal cross-branch jump). See nethack_core/curriculum_engine_env.py.

The curriculum is a 6-floor down / 6-floor up tour:

    floor:   1   2   3        4    5    6
    level:  DoD1 DoD2 DoD3 -> Geh48 Geh49 Geh50   (then back up)

Go-Explore natively maximizes depth, so to also reward the *ascent* we score
cells by TOUR PROGRESS: progress = floor while descending; once the bottom
(floor 6) has been reached along a cell's trajectory, progress = 6 + (6 - floor)
so climbing back up keeps increasing progress. A cell carries the max floor seen
on its trajectory (snapshot-independent metadata) to know which phase it's in.

Run::

    python approaches/go_explore/curriculum_go_explore.py \
        --iterations 400 --explore-steps 40 --seeds 19 2 9 --out outputs/curriculum_ge
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
from dataclasses import dataclass, field

_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "environments" / "nethack"))

from nethack_core.curriculum_engine_env import CurriculumEngineEnv  # noqa: E402

# Real game primitives only. Compass single-steps, a "run" in each compass
# direction (repeat the real move until blocked — what a human does holding the
# key; covers corridors so exploration actually traverses the level), search,
# and the real stair commands. No descend/ascend skill.
_COMPASS = [ord(c) for c in "hjklyubn"]
_RUN = [("run", c) for c in "hjklyubn"]          # run-macros
ACTIONS = list(_COMPASS) + _RUN + [ord("s"), ord(">"), ord("<")]
# Favor run-moves (roam toward stairs fast); over-weight `>`/`<` so that
# whenever the agent stands on a stair it tends to use it (off a stair: no-op).
WEIGHTS = [1.0] * len(_COMPASS) + [4.0] * len(_RUN) + [1.0, 3.0, 3.0]
_RUN_MAX = 12  # max tiles per run-macro


def _do_action(env, action):
    """Execute one Go-Explore action (single move / run-macro / command).
    Returns (obs, done). A run-macro repeats a real single move until the hero
    stops moving (blocked / event) — purely real movement, no skill."""
    if isinstance(action, tuple):  # ("run", direction)
        key = ord(action[1])
        obs = done = None
        last = None
        for _ in range(_RUN_MAX):
            obs, done, _info = env.step(key)
            pos = (int(obs.blstats[0]), int(obs.blstats[1]))
            if done or pos == last:   # blocked or something happened
                break
            last = pos
        return obs, done
    return env.step(action)[:2]

_CELL_GRID = 4
MAX_FLOOR = 6  # Gehennom 50 (bottom of the deep segment)
MAX_CELLS = 6000


def _xy(obs):
    return int(obs.blstats[0]), int(obs.blstats[1])


def _progress(floor: int, bottomed: bool) -> int:
    """Tour progress: descend 1..6, then ascend 6..11 (6 + floors climbed back)."""
    if floor <= 0:
        return 0
    return floor if not bottomed else MAX_FLOOR + (MAX_FLOOR - floor)


@dataclass
class Cell:
    handle: object
    progress: int
    max_floor: int          # deepest curriculum floor along this cell's trajectory
    traj: list
    n_visits: int = 0


@dataclass
class Result:
    n_cells: int
    deepest_floor: int      # max floors descended (1..6)
    climbed_back: int       # floors ascended from the bottom (0..6)
    reached_bottom: bool
    iterations: int
    timeseries: list = field(default_factory=list)


def _select(archive, rng):
    keys = list(archive.keys())
    weights = [(1.0 + archive[k].progress) / (1.0 + archive[k].n_visits) for k in keys]
    return rng.choices(keys, weights=weights, k=1)[0]


def _evict(env, archive):
    if len(archive) <= MAX_CELLS:
        return
    victims = sorted(archive, key=lambda k: (archive[k].progress, -len(archive[k].traj)))
    for k in victims[: len(archive) - MAX_CELLS]:
        try:
            env.free_snapshot(archive[k].handle)
        except Exception:
            pass
        del archive[k]


def run_curriculum_go_explore(*, iterations, explore_steps, seed, verbose=True):
    env = CurriculumEngineEnv()
    obs, _ = env.reset(seeds=(seed, seed))

    def key_of(obs, prog):
        x, y = _xy(obs)
        return (prog, int(obs.blstats[23]), x // _CELL_GRID, y // _CELL_GRID)

    start_floor = env.curriculum_floor(obs)
    start_prog = _progress(start_floor, False)
    archive = {key_of(obs, start_prog): Cell(env.snapshot(), start_prog, start_floor, [])}

    deepest = start_floor
    min_after_bottom = MAX_FLOOR
    reached_bottom = False
    timeseries = []
    rng = random.Random(seed)

    for it in range(iterations):
        key = _select(archive, rng)
        cell = archive[key]
        cell.n_visits += 1
        env.restore(cell.handle)
        env.engine.reseed(core=10_000 + it, disp=20_000 + it)

        running_max = cell.max_floor
        traj = list(cell.traj)
        done = False
        for _ in range(explore_steps):
            if done:
                break
            action = rng.choices(ACTIONS, weights=WEIGHTS, k=1)[0]
            try:
                obs, done = _do_action(env, action)
            except Exception:
                done = True
                break
            traj.append(action)
            floor = env.curriculum_floor(obs)
            if floor > 0:
                running_max = max(running_max, floor)
            bottomed = running_max >= MAX_FLOOR
            prog = _progress(floor, bottomed)
            nk = key_of(obs, prog)
            existing = archive.get(nk)
            if existing is None or prog > existing.progress or (
                prog == existing.progress and len(traj) < len(existing.traj)
            ):
                handle = env.snapshot()
                if existing is not None:
                    try:
                        env.free_snapshot(existing.handle)
                    except Exception:
                        pass
                archive[nk] = Cell(handle, prog, running_max, list(traj),
                                   existing.n_visits if existing else 0)

            if floor > 0:
                deepest = max(deepest, floor)
            if bottomed:
                reached_bottom = True
                if floor > 0:
                    min_after_bottom = min(min_after_bottom, floor)

        _evict(env, archive)
        climbed = (deepest - min_after_bottom) if reached_bottom else 0
        timeseries.append({"iter": it + 1, "deepest_floor": deepest,
                           "climbed_back": climbed, "cells": len(archive)})
        if verbose and (it + 1) % 25 == 0:
            print(f"[iter {it + 1:4d}] cells={len(archive):4d} "
                  f"deepest_floor={deepest}/6 climbed_back={climbed}")

    try:
        env.close()
    except Exception:
        pass
    return Result(len(archive), deepest, (deepest - min_after_bottom) if reached_bottom else 0,
                  reached_bottom, iterations, timeseries)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=400)
    ap.add_argument("--explore-steps", type=int, default=40)
    ap.add_argument("--seeds", type=int, nargs="+", default=[19])
    ap.add_argument("--out", default="outputs/curriculum_ge")
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = []
    for seed in args.seeds:
        print(f"=== Go-Explore curriculum: seed {seed} ===")
        res = run_curriculum_go_explore(iterations=args.iterations,
                                        explore_steps=args.explore_steps, seed=seed)
        rec = {"algo": "go_explore", "seed": seed,
               "deepest_floor": res.deepest_floor, "climbed_back": res.climbed_back,
               "reached_bottom": res.reached_bottom, "iterations": res.iterations,
               "n_cells": res.n_cells, "timeseries": res.timeseries}
        (out / f"go_explore_seed{seed}.json").write_text(json.dumps(rec, indent=2))
        summary.append({k: rec[k] for k in
                        ("seed", "deepest_floor", "climbed_back", "reached_bottom")})
        print(f"  -> deepest_floor={res.deepest_floor}/6 climbed_back={res.climbed_back} "
              f"reached_bottom={res.reached_bottom}")
    (out / "go_explore_summary.json").write_text(json.dumps(summary, indent=2))
    print("summary:", json.dumps(summary))


if __name__ == "__main__":
    main()
