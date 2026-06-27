"""Reverse-curriculum reachability sweep on the compressed NetHack tour.

Research question
-----------------
What curriculum lets an LLM agent learn to traverse the compressed NetHack tour
using ONLY legal game primitives (move/search/real-stairs), WITHOUT ever being
handed an illegal ascend/descend skill?

We measure the *difficulty landscape* of the CLIMB (the "go backwards" half the
agent must learn). Every condition is a pure climb task: the agent is constructed
at curriculum floor ``s`` (via the internal ``goto_abs`` cheat + the deep
stats-upgrade — used ONLY to build the start state, never exposed to the agent),
then must climb back to floor 1 (the top) using real ``<`` stairs it navigates to
itself. Approach B: the episode runs from the start all the way to the goal
(reach floor 1), or until death / the step budget.

Conditions
----------
  climb_from_2 .. climb_from_6 : start at floor s, climb to floor 1.
  full_tour                    : start at floor 1, DESCEND to the bottom then
                                 climb back (the no-curriculum baseline — the
                                 whole task at once).

The contrast across start depth answers the curriculum question: if near-goal
climbs (small s) succeed while deep starts and full_tour fail, a reverse
curriculum (start near the goal, extend the horizon backward) is the curriculum
that works. The floor-4->3 boundary is the internal Gehennom<->DoD cross-branch
jump-up — a natural difficulty cliff to look for.

The agent, tools, prompt, and metric reuse curriculum_voyager.py verbatim; this
module only adds (a) start-state construction at an arbitrary floor and (b) a
climb-goal episode loop with early termination, plus a parallel launcher.

Run one episode (subprocess-isolated; the NetHack C engine is process-global):
    PI_API_KEY=... python reverse_curriculum_sweep.py --single climb_from_4 19 0 \
        --out outputs/.../ep.json

Launch the whole sweep (process pool):
    PI_API_KEY=... python reverse_curriculum_sweep.py --launch \
        --seeds 19 2 9 --reps 4 --workers 6 --out outputs/.../reverse_curriculum
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import pathlib
import subprocess
import sys
import time

import numpy as np

_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "environments" / "nethack"))
sys.path.insert(0, str(_ROOT / "approaches" / "voyager"))

import curriculum_voyager as cv  # noqa: E402  (agent loop, tools, prompt, _glm)
from nethack_core.curriculum_engine_env import CurriculumEngineEnv  # noqa: E402

MODEL_DEFAULT = "z-ai/glm-5.2"

# Endpoints. Model id prefix selects the backend + key:
#   gemini-*  -> Google Generative Language OpenAI-compatible endpoint (GEMINI_API_KEY)
#   else      -> Prime Inference (PI_API_KEY / REFINER_API_KEY)
_PRIME_BASE = "https://api.pinference.ai/api/v1"
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"


def _endpoint_for(model: str):
    if model.startswith("gemini"):
        return _GEMINI_BASE, os.environ.get("GEMINI_API_KEY", "")
    return _PRIME_BASE, (os.environ.get("PI_API_KEY")
                         or os.environ.get("REFINER_API_KEY") or "")


class LLMError(RuntimeError):
    pass


def llm_call(model, messages, *, max_tokens=2000, retries=5):
    """One chat-completion call with exponential backoff on transient errors.

    Retries 429 (rate limit) and 5xx with backoff. Raises LLMError immediately on
    402 (payment / out of credits) — retrying that is pointless and it must be
    surfaced, not silently turned into a no-op turn (the bug that nulled whole
    episodes when Prime ran out of credits mid-sweep)."""
    import time as _t
    import urllib.request
    base, key = _endpoint_for(model)
    body = json.dumps({
        "model": model, "messages": messages,
        "max_tokens": max_tokens, "temperature": 0.6,
        "response_format": {"type": "json_object"},
    }).encode()
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(
            f"{base}/chat/completions", data=body,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json",
                     "User-Agent": "curl/8.4.0"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read())
            return d["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            code = e.code
            if code == 402:
                raise LLMError("402 Payment Required (account out of credits)")
            if code in (429, 500, 502, 503, 529):
                last = f"HTTP {code}"
                _t.sleep(min(2 ** attempt + attempt, 30))
                continue
            raise LLMError(f"HTTP {code}: {e.read()[:120]!r}")
        except Exception as e:                       # noqa: BLE001
            last = str(e)[:80]
            _t.sleep(min(2 ** attempt, 20))
    raise LLMError(f"exhausted {retries} retries: {last}")

# Conditions: name -> (start_floor, max_turns). max_turns scales with the climb
# distance (turns/floor budget set generously from the ~6.7s/turn smoke test).
CONDITIONS: dict[str, tuple[int, int]] = {
    "climb_from_2": (2, 45),
    "climb_from_3": (3, 70),
    "climb_from_4": (4, 95),
    "climb_from_5": (5, 115),
    "climb_from_6": (6, 140),
    "full_tour":    (1, 200),
}

# Climb-task system prompt: the agent starts deep and must climb UP. (The stock
# curriculum_voyager SYSTEM tells the agent to descend first, which is right only
# for full_tour; for the constructed climb starts we want a climb-only goal.)
CLIMB_SYSTEM = """You are playing NetHack as a female neutral Valkyrie with FULL
VISION (the whole level is visible). You START DEEP in the dungeon. GOAL: climb
back UP to dungeon level 1 (the top) as fast as you can, using the real up
stairs '<'. Taking the up stairs '<' near the top of the deep region jumps you
back toward the surface automatically; just keep finding and taking '<'.

Tools (real NetHack primitives — YOU decide how to use them):
- move_to(x, y): walk to tile (x,y) along VISIBLY-OPEN terrain (floor, corridor,
  open doorway, stairs). Plain navigation: it does NOT open/kick doors, attack
  monsters, or push through anything. If blocked it STOPS and tells you what's
  adjacent (a closed door '+', a monster, etc.) and which way the target is.
- move(direction): one real step (N,S,E,W,NE,NW,SE,SW). Stepping into a monster
  ATTACKS it; into your pet swaps places.
- open(direction): open an adjacent closed door '+'.
- kick(direction): kick an adjacent door (use when open says it's LOCKED).
- search(times): search adjacent tiles for hidden passages/doors.
- stairs_up / stairs_down: take the real '<' / '>' (must be standing on it).

STRATEGY: To climb — move_to a visible '<', then stairs_up. When move_to stops
"blocked", read what it reports and decide: a closed door -> open(dir) (locked ->
kick(dir)); a monster -> move(dir) to attack it until gone; no route -> search
for a hidden passage or pick a different tile to move_to. Then continue to the '<'.

Respond with ONLY a JSON object, e.g. {"tool":"move_to","x":50,"y":16},
{"tool":"move","direction":"SW"}, {"tool":"open","direction":"W"},
{"tool":"stairs_up"}."""


def _floor_to_abs(env: CurriculumEngineEnv, floor: int) -> tuple[int, int]:
    """Map curriculum floor 1..6 to (dnum, dlevel) for goto_abs.

    1-3 -> Dungeons of Doom depth 1/2/3; 4-6 -> Gehennom deep_lo + (floor-4)."""
    if floor <= 3:
        return env._dod_dnum, floor
    geh_depth = env._deep_lo + (floor - 4)
    return env._geh_dnum, geh_depth - env._geh_start + 1


def construct_start(env: CurriculumEngineEnv, obs, start_floor: int):
    """Build the start state at ``start_floor`` using the internal cheat.

    For climb starts (floor >= 2) we teleport there AND apply the deep
    stats-upgrade, so the constructed hero matches one that legitimately descended
    and is now climbing back (consistent survivability). floor 1 = the natural
    reset (full_tour); no teleport, no upgrade — the env applies the upgrade itself
    at the real jump-down."""
    if start_floor <= 1:
        return obs
    dnum, dlevel = _floor_to_abs(env, start_floor)
    env.goto_abs(dnum, dlevel)
    obs = env.modify(**env._sample_upgrade())
    # Guard: some seeds' goto_abs silently lands on floor 1 instead of the
    # target (observed on seed 22), which would fake a full-climb "win". Reject
    # any construct that did not land on the intended floor.
    got = env.curriculum_floor(obs)
    if got != start_floor:
        raise ValueError(
            f"construct for floor {start_floor} landed on floor {got} "
            f"(invalid goto_abs); skip this (seed, floor) cell")
    return obs


import numpy as _np
from nethack_core.glyphs import (  # noqa: E402
    CMAP_CLOSED_DOOR_INDICES, GLYPH_CMAP_OFF, glyph_is_cmap,
)

_CLOSED = set(int(i) for i in CMAP_CLOSED_DOOR_INDICES)
# cmap indices 12-16 = doorway, open door (V/H), closed door (V/H). NetHack
# forbids moving DIAGONALLY into or out of any of these, so the pathfinder must
# only ever approach/leave a door orthogonally.
_DOORISH = frozenset({12, 13, 14, 15, 16})


def _is_closed_door(glyphs, x, y) -> bool:
    g = int(glyphs[y, x])
    return glyph_is_cmap(_np.int64(g)) and (g - GLYPH_CMAP_OFF) in _CLOSED


def _walk_open_doors(glyphs):
    """walkview that ALSO treats closed doors as passable, so A* routes a path
    THROUGH them — nav_to then opens each door as it reaches it (a legal `open`,
    not a new capability; it just saves the agent from fumbling doors by hand)."""
    wv = cv._walkview(glyphs)
    cd = _np.zeros(glyphs.shape, bool)
    g = _np.asarray(glyphs).astype(_np.int64)
    cm = glyph_is_cmap(g)
    idx = g - GLYPH_CMAP_OFF
    for ci in _CLOSED:
        cd |= cm & (idx == ci)
    wv = wv.copy()
    wv[cd] = ord(".")
    return wv


# 8 neighbours as (dx, dy, step-key, is_diagonal).
_NEI8 = [(0, -1, ord("k"), False), (0, 1, ord("j"), False),
         (-1, 0, ord("h"), False), (1, 0, ord("l"), False),
         (-1, -1, ord("y"), True), (1, -1, ord("u"), True),
         (-1, 1, ord("b"), True), (1, 1, ord("n"), True)]


def _door_mask(glyphs):
    g = _np.asarray(glyphs).astype(_np.int64)
    cm = glyph_is_cmap(g)
    idx = g - GLYPH_CMAP_OFF
    m = _np.zeros(g.shape, bool)
    for di in _DOORISH:
        m |= cm & (idx == di)
    return m


def _bfs_path(walk, door, start, goal):
    """BFS shortest path (list of step-keys) with NetHack movement rules:
    8-connectivity, but a DIAGONAL step is forbidden when the source OR the
    destination tile is a door/doorway. Closed doors are passable in ``walk`` and,
    because they are doorish, are only ever entered orthogonally — so nav_to can
    always open them with an orthogonal `open`."""
    from collections import deque
    sx, sy = start
    gx, gy = goal
    H, W = walk.shape
    seen = {(sx, sy)}
    q = deque([(sx, sy, [])])
    while q:
        x, y, path = q.popleft()
        if (x, y) == (gx, gy):
            return path
        here_door = door[y, x]
        for dx, dy, key, diag in _NEI8:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < W and 0 <= ny < H) or (nx, ny) in seen:
                continue
            # blocked = wall '|' OR space ' ' (the char-LUT collapses solid stone
            # AND dark floor to ' '; with reveal_map the level is lit, so ' ' is
            # effectively always un-walkable stone — the engine refuses to enter).
            if (nx, ny) != (gx, gy) and walk[ny, nx] in (ord("|"), ord(" ")):
                continue
            if diag and (here_door or door[ny, nx]):
                continue                       # no diagonal in/out of a doorway
            seen.add((nx, ny))
            q.append((nx, ny, path + [key]))
    return []


def nav_to(env, x, y, max_steps: int = 200):
    """Door-aware ORTHOGONAL navigation: BFS over terrain where closed doors are
    passable; walk it, opening (or kicking, if locked) any closed door on the
    path. Stops and reports if a MONSTER blocks the next tile (combat stays the
    agent's call) or there is no route. Never descends/ascends — movement + doors
    only (both legal primitives the agent already has)."""
    tx, ty = int(x), int(y)
    obs = env._engine.to_core_observation()
    for _ in range(max_steps):
        cx, cy = cv._pos(obs)
        if (cx, cy) == (tx, ty):
            return obs, False, f"reached ({tx},{ty})"
        glyphs = _np.array(obs.glyphs).reshape(21, 79)
        chars = _np.array(obs.chars).reshape(21, 79)
        wv = _walk_open_doors(glyphs)
        path = _bfs_path(wv, _door_mask(glyphs), (cx, cy), (tx, ty))
        if not path:
            return obs, False, cv._blocker_hint(chars, (cx, cy), (tx, ty))
        key = path[0]
        dx, dy = cv._DIRS[key]
        nx, ny = cx + dx, cy + dy
        ch = chr(int(chars[ny, nx]))
        if cv._is_monster(ch) and ch != "@":          # let the agent fight
            return obs, False, cv._blocker_hint(chars, (cx, cy), (tx, ty))
        if _is_closed_door(glyphs, nx, ny):
            env.step(ord("o")); o2, done, _ = env.step(key)   # open (orthogonal)
            msg = bytes(o2.message).split(b"\x00")[0].decode("latin1")
            obs = o2
            if done:
                return obs, True, "died opening a door"
            if "locked" in msg.lower():
                env.step(4); o3, done, _ = env.step(key)       # kick it in
                obs = o3
                if done:
                    return obs, True, "died kicking a door"
            continue
        obs, done, moved = cv._try(env, key)
        if done:
            return obs, True, "died en route"
        if not moved:
            return obs, False, cv._blocker_hint(chars, (cx, cy), (tx, ty))
    return obs, False, f"still en route to ({tx},{ty})"


def exec_climb(env, action):
    """Like curriculum_voyager._exec but routes move_to through the door-aware
    nav_to. All other tools (move/open/kick/search/stairs) are unchanged."""
    if action.get("tool") == "move_to":
        return nav_to(env, action.get("x", 0), action.get("y", 0))
    return cv._exec(env, action)


def render_climb(env: CurriculumEngineEnv, obs):
    """Climb-oriented view: same map as curriculum_voyager._render, but the hint
    points at the UP stair (the goal of a climb), not the down stair.

    curriculum_voyager._render is descent-biased — whenever a down stair is
    visible (i.e. almost always) it tells the agent to go to it, which actively
    misleads a climbing agent. We reuse its map text (everything before the
    ">>> " hint marker) and substitute a climb hint."""
    full, hero, downs, ups = cv._render(env, obs)
    head = full.split(">>> ", 1)[0]
    on = env._engine.hero_on_stair()  # +1 down, -1 up, 0 none
    if on == -1:
        hint = "You are STANDING ON the up stair '<' — call stairs_up NOW to climb."
    elif ups:
        hint = (f"Nearest goal: move_to the up stair '<' at {ups[0]}, then "
                f"stairs_up. You are NOT on an up stair yet. IGNORE the down "
                f"stairs — your goal is to climb UP, not down.")
    elif downs:
        hint = ("No up stair '<' visible on this level yet. Explore with move_to "
                "/ search to find a '<'. Do NOT take the down stairs '>'.")
    else:
        hint = "No stairs visible — explore with move_to / search to find a '<'."
    return head + ">>> " + hint, hero, downs, ups


def run_episode(*, condition: str, seed: int, rep: int, model: str, api_key: str):
    """Run one episode and return a result dict (+ full per-turn timeseries)."""
    start_floor, max_turns = CONDITIONS[condition]
    is_climb = start_floor >= 2
    system = CLIMB_SYSTEM if is_climb else cv.SYSTEM

    env = CurriculumEngineEnv()
    obs, _ = env.reset(seeds=(seed, seed))
    obs = construct_start(env, obs, start_floor)

    f0 = env.curriculum_floor(obs)
    deepest = f0
    min_floor = f0                     # shallowest (= highest up) floor seen
    min_after_bottom = cv.MAX_FLOOR
    reached_bottom = False
    reached_top = (f0 == 1)
    t_start = time.time()
    latencies: list[float] = []
    timeseries = []
    if is_climb:
        last = (f"Begin. You start DEEP at curriculum floor {f0}. GOAL: climb "
                f"UP to dungeon level 1 using the up stairs '<'.")
    else:
        last = "Begin."

    render = render_climb if is_climb else cv._render
    llm_error = None
    for turn in range(max_turns):
        view, _pos, _downs, _ups = render(env, obs)
        user = f"{view}\n\nLast action result: {last}\nWhat is your next tool call?"
        t = time.time()
        try:
            content = llm_call(model, [{"role": "system", "content": system},
                                       {"role": "user", "content": user}])
        except LLMError as exc:
            # A hard LLM failure (out of credits, retries exhausted) must ABORT
            # the episode — not run pointless no-op turns that masquerade as data.
            llm_error = str(exc)
            break
        except Exception as exc:               # noqa: BLE001
            content = "{}"
            last = f"(LLM error: {str(exc)[:80]})"
        latencies.append(time.time() - t)
        action = cv._parse(content)
        try:
            obs, done, last = exec_climb(env, action)
        except Exception as exc:               # noqa: BLE001
            done, last = False, f"(tool error: {str(exc)[:80]})"

        floor = env.curriculum_floor(obs)
        if floor > 0:
            deepest = max(deepest, floor)
            min_floor = min(min_floor, floor)
            if floor == 1:
                reached_top = True
        if deepest >= cv.MAX_FLOOR:
            reached_bottom = True
            if floor > 0:
                min_after_bottom = min(min_after_bottom, floor)
        timeseries.append({"turn": turn + 1, "tool": action.get("tool"),
                           "floor": floor, "deepest_floor": deepest,
                           "min_floor": min_floor})
        if done:
            last = "(You died — episode ended.)"
            break
        if is_climb and reached_top:
            last = "(Reached dungeon level 1 — climb complete.)"
            break

    died = bool(timeseries) and "died" in last.lower()
    # floors_climbed: how many floors up from the start the agent achieved.
    floors_climbed = max(0, f0 - min_floor) if is_climb else (
        (deepest - min_after_bottom) if reached_bottom else 0)
    return {
        "condition": condition, "seed": seed, "rep": rep, "model": model,
        "start_floor": f0, "max_turns": max_turns,
        "reached_top": bool(reached_top),
        "deepest_floor": deepest, "min_floor": min_floor,
        "floors_climbed": int(floors_climbed),
        "reached_bottom": bool(reached_bottom), "died": died,
        "llm_error": llm_error,
        "turns": len(timeseries),
        "wall_s": round(time.time() - t_start, 1),
        "mean_turn_s": round(float(np.mean(latencies)), 2) if latencies else 0.0,
        "timeseries": timeseries,
    }


# --------------------------------------------------------------------------- #
# CLI: single-episode worker  +  parallel launcher
# --------------------------------------------------------------------------- #
def _single(args):
    api_key = os.environ.get("PI_API_KEY") or os.environ.get("REFINER_API_KEY")
    if not api_key:
        raise SystemExit("set PI_API_KEY")
    condition, seed, rep = args.single
    res = run_episode(condition=condition, seed=int(seed), rep=int(rep),
                      model=args.model, api_key=api_key)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2))
    r = res
    print(f"DONE {condition} seed{seed} rep{rep}: reached_top={r['reached_top']} "
          f"climbed={r['floors_climbed']} deepest={r['deepest_floor']} "
          f"turns={r['turns']} {r['wall_s']}s", flush=True)


def _launch(args):
    out = pathlib.Path(args.out)
    (out / "episodes").mkdir(parents=True, exist_ok=True)
    results_path = out / "results.ndjson"
    conditions = args.conditions or list(CONDITIONS.keys())
    plan = [(c, s, r) for c in conditions for s in args.seeds
            for r in range(args.reps)]
    print(f"[launch] {len(plan)} episodes, {args.workers} workers -> {out}",
          flush=True)

    def worker(cell):
        condition, seed, rep = cell
        ep_path = out / "episodes" / f"{condition}_seed{seed}_rep{rep}.json"
        if ep_path.is_file() and not args.overwrite:
            return json.loads(ep_path.read_text())  # resume: skip done cells
        cmd = [sys.executable, __file__, "--single", condition, str(seed),
               str(rep), "--model", args.model, "--out", str(ep_path)]
        env = dict(os.environ)
        t = time.time()
        p = subprocess.run(cmd, env=env, capture_output=True, text=True,
                           timeout=args.episode_timeout)
        if p.returncode != 0 or not ep_path.is_file():
            return {"condition": condition, "seed": seed, "rep": rep,
                    "error": (p.stderr or p.stdout or "no output")[-400:],
                    "wall_s": round(time.time() - t, 1)}
        return json.loads(ep_path.read_text())

    done = 0
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(worker, cell): cell for cell in plan}
        with results_path.open("a") as fh:
            for fut in cf.as_completed(futs):
                cell = futs[fut]
                try:
                    res = fut.result()
                except Exception as exc:        # noqa: BLE001
                    res = {"condition": cell[0], "seed": cell[1], "rep": cell[2],
                           "error": f"future: {str(exc)[:300]}"}
                done += 1
                slim = {k: v for k, v in res.items() if k != "timeseries"}
                fh.write(json.dumps(slim) + "\n"); fh.flush()
                tag = ("ERR " + res["error"][:60]) if res.get("error") else (
                    f"top={res.get('reached_top')} climbed={res.get('floors_climbed')} "
                    f"deepest={res.get('deepest_floor')} {res.get('wall_s')}s")
                print(f"[{done}/{len(plan)}] {cell[0]} seed{cell[1]} rep{cell[2]}: "
                      f"{tag}", flush=True)
    print(f"[launch] complete: {done} episodes -> {results_path}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--single", nargs=3, metavar=("CONDITION", "SEED", "REP"),
                    help="run ONE episode (subprocess worker)")
    ap.add_argument("--launch", action="store_true", help="run the full sweep")
    ap.add_argument("--seeds", type=int, nargs="+", default=[19, 2, 9])
    ap.add_argument("--reps", type=int, default=4)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--conditions", nargs="+", default=None)
    ap.add_argument("--model", default=MODEL_DEFAULT)
    ap.add_argument("--episode-timeout", type=int, default=3000)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--out", default="outputs/curriculum_experiments/reverse_curriculum")
    args = ap.parse_args()
    if args.single:
        _single(args)
    elif args.launch:
        _launch(args)
    else:
        ap.error("pass --single or --launch")


if __name__ == "__main__":
    main()
