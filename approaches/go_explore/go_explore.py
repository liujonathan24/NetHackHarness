"""Go-Explore driver for NetHack — KEYLESS (no API/LLM cost).

Classic "first return, then explore" (Ecoffet et al. 2021) over the fork
engine's byte-exact in-memory snapshot/restore API (see
``nethack_core/engine_env.py`` and ``environments/nethack/tests/test_snapshot.py``).

The loop:
    1. ARCHIVE   — dict ``cell_key -> Cell`` where a cell holds a snapshot
                   handle, depth, visit count and the trajectory (action list)
                   that first reached it.
    2. INIT      — reset the env, snapshot, archive the start cell.
    3. LOOP      — for ``iterations`` iterations:
         a. SELECT  a promising cell (bias toward deeper / less-visited cells:
                    weight ~ (1 + depth) / (1 + visits)).
         b. RETURN  restore(cell.handle); reseed after restore so random chance
                    diverges across returns (mirrors EngineEnv.branch()).
         c. EXPLORE take K random actions from a small set (8 compass moves +
                    search + descend); after each step compute the new cell key
                    + depth.
         d. ARCHIVE any newly-reached cell (snapshot it); update a known cell if
                    reached deeper or via a shorter trajectory.
         e. TRACK   the global best depth and the action sequence reaching it.

Snapshots are freed when a cell is evicted (the archive is capped) and when a
fresh snapshot replaces a cell's old one, so handles do not leak.

blstats indices (verified empirically against the fork engine):
    blstats[0]  = player x
    blstats[1]  = player y
    blstats[12] = dungeon depth (dlvl)
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
from dataclasses import dataclass, field
from typing import Optional

from nethack_core.engine_env import EngineEnv

# blstats indices (see module docstring / core.py).
_BL_X = 0
_BL_Y = 1
_BL_DEPTH = 12

# Coarse-position cell discretisation: nearby tiles share a cell. A finer grid
# rewards incremental movement (each ~GRID-tile step opens a new frontier cell
# to return to), which is what lets short random explorations compound into
# reaching far rooms / downstairs rather than rattling inside one room.
_CELL_GRID = 4

# Action set explored from a returned-to cell.
#   8 compass moves (raw ASCII: h j k l y u b n), search 's', descend '>'.
_COMPASS = [ord(c) for c in "hjklyubn"]
_SEARCH = ord("s")
_DESCEND = ord(">")
EXPLORE_ACTIONS = _COMPASS + [_SEARCH, _DESCEND]

# Sampling weights: favour movement (to roam toward stairs), keep search rare,
# and over-weight descend so that whenever the agent happens to stand on a
# downstair it is likely to take it (descending off a stair is the only way to
# gain depth; off a stair it is a harmless no-op).
_ACTION_WEIGHTS = [4.0] * len(_COMPASS) + [1.0, 3.0]

# Keep at most this many cells; evict the lowest-value ones (frees snapshots).
_MAX_ARCHIVE = 200


def _depth_of(obs) -> int:
    try:
        return int(obs.blstats[_BL_DEPTH])
    except Exception:
        return 0


def _pos_of(obs) -> tuple[int, int]:
    try:
        return int(obs.blstats[_BL_X]), int(obs.blstats[_BL_Y])
    except Exception:
        return 0, 0


def cell_key(obs) -> tuple[int, int, int]:
    """Coarse cell descriptor: (dungeon_level, x // GRID, y // GRID)."""
    x, y = _pos_of(obs)
    return (_depth_of(obs), x // _CELL_GRID, y // _CELL_GRID)


@dataclass
class Cell:
    handle: object              # EngineEnv snapshot handle
    depth: int
    traj: list[int]             # action sequence from start that reached the cell
    n_visits: int = 0
    pos: tuple[int, int] = (0, 0)


@dataclass
class Result:
    n_cells: int
    max_depth: int
    best_traj: list[int]
    best_depth_cell: tuple[int, int, int]
    iterations: int
    explore_steps: int
    seed: int
    trace_path: str = ""
    cell_keys: list = field(default_factory=list)


def _select_cell(archive: dict, rng: random.Random) -> tuple:
    """Weighted-random pick biased toward deeper / less-visited cells.

    weight = (1 + depth) / (1 + n_visits)  — deeper cells and cells we have
    returned to less often are more attractive.
    """
    keys = list(archive.keys())
    weights = [
        (1.0 + archive[k].depth) / (1.0 + archive[k].n_visits) for k in keys
    ]
    return rng.choices(keys, weights=weights, k=1)[0]


def _evict_if_needed(env: EngineEnv, archive: dict) -> None:
    """Cap the archive size; evict lowest-value cells and free their snapshots.

    Value mirrors selection: prefer keeping deep, lightly-visited cells. The
    start cell is never evicted while it is the only shallowest anchor — but the
    generic rule already keeps it if nothing deeper exists.
    """
    while len(archive) > _MAX_ARCHIVE:
        # Lowest (depth, then shortest traj) is the least valuable to keep.
        victim = min(
            archive,
            key=lambda k: (archive[k].depth, -len(archive[k].traj)),
        )
        cell = archive.pop(victim)
        try:
            env.free_snapshot(cell.handle)
        except Exception:
            pass


def run_go_explore(
    *,
    iterations: int,
    explore_steps: int,
    seed: int,
    verbose: bool = True,
) -> tuple[Result, EngineEnv]:
    """Run the archive→return→explore loop. Returns (Result, env).

    The env is returned open so the caller can replay the best trajectory for
    trace rendering; the caller is responsible for closing it.
    """
    rng = random.Random(seed)

    env = EngineEnv()
    env.seed(seed, seed)
    obs, _meta = env.reset()

    start_key = cell_key(obs)
    archive: dict[tuple, Cell] = {
        start_key: Cell(
            handle=env.snapshot(),
            depth=_depth_of(obs),
            traj=[],
            n_visits=0,
            pos=_pos_of(obs),
        )
    }

    best_depth = _depth_of(obs)
    best_traj: list[int] = []
    best_cell = start_key

    for it in range(iterations):
        key = _select_cell(archive, rng)
        cell = archive[key]
        cell.n_visits += 1

        # RETURN: restore the cell's snapshot, then reseed so chance diverges.
        env.restore(cell.handle)
        env.engine.reseed(core=10_000 + it, disp=20_000 + it)

        traj = list(cell.traj)
        done = False
        # EXPLORE: K random actions from the small action set.
        for _ in range(explore_steps):
            if done:
                break
            action = rng.choices(EXPLORE_ACTIONS, weights=_ACTION_WEIGHTS, k=1)[0]
            try:
                obs, done, _info = env.step(action)
            except Exception:
                done = True
                break
            traj.append(action)

            depth = _depth_of(obs)
            new_key = cell_key(obs)
            existing = archive.get(new_key)

            # ARCHIVE / UPDATE: new cell, or a better (deeper / shorter) route.
            better = existing is None or (
                depth > existing.depth
                or (depth == existing.depth and len(traj) < len(existing.traj))
            )
            if better:
                new_handle = env.snapshot()
                if existing is not None:
                    try:
                        env.free_snapshot(existing.handle)
                    except Exception:
                        pass
                archive[new_key] = Cell(
                    handle=new_handle,
                    depth=depth,
                    traj=list(traj),
                    n_visits=existing.n_visits if existing is not None else 0,
                    pos=_pos_of(obs),
                )

            # TRACK global best: deeper wins; at equal depth, a shorter
            # trajectory wins.
            if depth > best_depth or (
                depth == best_depth and len(traj) < len(best_traj)
            ):
                best_depth = depth
                best_traj = list(traj)
                best_cell = new_key

        _evict_if_needed(env, archive)

        if verbose and (it + 1) % 25 == 0:
            print(
                f"[iter {it + 1:4d}] cells={len(archive):4d} "
                f"best_depth={best_depth} best_traj_len={len(best_traj)}"
            )

    result = Result(
        n_cells=len(archive),
        max_depth=best_depth,
        best_traj=best_traj,
        best_depth_cell=best_cell,
        iterations=iterations,
        explore_steps=explore_steps,
        seed=seed,
        cell_keys=sorted(archive.keys()),
    )
    return result, env


# --------------------------------------------------------------------------- #
# Trace writing (viewer-compatible NDJSON of the BEST trajectory).
# --------------------------------------------------------------------------- #

def _raw_grid(obs) -> list[str]:
    """24x80 tty grid as rstrip'd strings (mirrors LiveStepper._raw_grid)."""
    try:
        return [
            "".join(chr(int(c)) for c in row).rstrip() for row in obs.tty_chars
        ]
    except Exception:
        return []


def _rendered_user_content(obs, action: Optional[int]) -> str:
    """Minimal but inspectable per-turn text: MAP + STATUS + last action."""
    grid = _raw_grid(obs)
    x, y = _pos_of(obs)
    depth = _depth_of(obs)
    act_label = ""
    if action is not None:
        act_label = repr(chr(action)) if 32 <= action < 127 else str(action)
    parts = [
        "=== MAP ===",
        "\n".join(grid),
        "",
        "=== STATUS ===",
        f"Dlvl: {depth}  Pos: ({x},{y})"
        + (f"  Action: {act_label}" if act_label else ""),
    ]
    return "\n".join(parts)


def write_trace(env: EngineEnv, result: Result, *, seed: int) -> str:
    """Replay the best trajectory from a fresh seed and write viewer NDJSON.

    Each line: {"turn", "raw_grid", "rendered_user_content", "variant",
    "dlvl", "pos", "action"} — the first four match the viewer's minimal
    format; the trailing three keep the run inspectable even without rendering.
    """
    out_dir = pathlib.Path(
        "environments/nethack/outputs/web_play"
    ) / f"go_explore_seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Replay deterministically from a fresh env (best_traj is the action prefix
    # from start). No reseed: byte-exact replay reproduces the recorded run.
    replay = EngineEnv()
    replay.seed(seed, seed)
    obs, _meta = replay.reset()

    lines: list[str] = []

    def record(turn: int, ob, action: Optional[int]) -> None:
        x, y = _pos_of(ob)
        lines.append(
            json.dumps(
                {
                    "turn": turn,
                    "raw_grid": _raw_grid(ob),
                    "rendered_user_content": _rendered_user_content(ob, action),
                    "variant": "B1",
                    "dlvl": _depth_of(ob),
                    "pos": [x, y],
                    "action": action,
                }
            )
        )

    record(0, obs, None)
    done = False
    for i, action in enumerate(result.best_traj, start=1):
        if done:
            break
        try:
            obs, done, _info = replay.step(action)
        except Exception:
            break
        record(i, obs, action)

    rid = f"go_explore_seed{seed}"
    (out_dir / f"{rid}.ndjson").write_text("\n".join(lines))
    replay.close()
    return str(out_dir / f"{rid}.ndjson")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Go-Explore driver (keyless).")
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--explore-steps", type=int, default=8)
    parser.add_argument("--seed", type=int, default=2)
    parser.add_argument(
        "--no-trace", action="store_true", help="skip writing the NDJSON trace"
    )
    args = parser.parse_args(argv)

    result, env = run_go_explore(
        iterations=args.iterations,
        explore_steps=args.explore_steps,
        seed=args.seed,
    )

    trace_path = ""
    if not args.no_trace:
        trace_path = write_trace(env, result, seed=args.seed)
        result.trace_path = trace_path

    env.close()

    print("\n=== Go-Explore result ===")
    print(f"seed              : {args.seed}")
    print(f"iterations        : {args.iterations}")
    print(f"explore_steps     : {args.explore_steps}")
    print(f"cells discovered  : {result.n_cells}")
    print(f"max depth reached : {result.max_depth}")
    print(f"best-traj length  : {len(result.best_traj)}")
    print(f"best-depth cell   : {result.best_depth_cell}  (dlvl, x//8, y//8)")
    if trace_path:
        print(f"trace             : {trace_path}")


if __name__ == "__main__":
    main()
