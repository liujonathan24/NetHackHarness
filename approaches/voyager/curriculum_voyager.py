"""Voyager-style LLM agent on the compressed curriculum, measuring how deep it
descends AND how far it climbs back up over time — using ONLY real game commands.

The agent (GLM via Prime Inference) plays a female-neutral Valkyrie with FULL
VISION. It is given NO descend/ascend skill and NO auto-descend. Its tools are:

  * move_to(x, y)  — navigate to a tile via A* over the real map (real compass
                     moves only; never auto-descends).
  * stairs_down    — take the real `>` (only works while standing on a `>`).
  * stairs_up      — take the real `<` (only works while standing on a `<`).
  * search(times)  — search for hidden passages.

So to go down the agent must SEE the down stair (full vision), navigate ONTO it,
then take it — exactly the "navigate + use the real stairs" loop. The curriculum
env redirects only at the 3<->48 boundary (internal cross-branch jump); the agent
just takes the real stairs. This is the Voyager idea — the LLM composes the
move_to + stairs primitives into a descend/ascend behavior it isn't handed.

Run (needs PI_API_KEY = the Prime api_key)::

    PI_API_KEY=$(python -c "import json,os;print(json.load(open(os.path.expanduser('~/.prime/config.json')))['api_key'])") \
    python approaches/voyager/curriculum_voyager.py --seeds 19 2 9 --max-turns 60 \
        --model z-ai/glm-5.2 --out outputs/curriculum_experiments/voyager
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.request

import numpy as np

_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "environments" / "nethack"))

from nethack_core.curriculum_engine_env import CurriculumEngineEnv  # noqa: E402
from nethack_harness.navigation.pathfinding import a_star, reachable_set  # noqa: E402

BASE_URL = "https://api.pinference.ai/api/v1"
MAX_FLOOR = 6

SYSTEM = """You are playing NetHack as a female neutral Valkyrie with FULL VISION
(the whole level is visible). GOAL: descend as DEEP as possible, then climb back
UP. Taking the down stairs on dungeon level 3 jumps you deep into the game
automatically; keep going down to the bottom, then turn around and climb all the
way back up.

Tools (no auto-descend, no "descend" skill):
- move_to(x, y): A* path to tile (x,y) over the visible map and walk it. It
  follows floor/corridor/door tiles only. It will FAIL when the route is blocked:
  if a MONSTER (a letter like d, x, @) sits on the only doorway/corridor, A* sees
  no walkable path and returns "no path"/"blocked by '<letter>'", because it
  won't path through a monster.
- move(direction): take ONE real step in a compass direction
  (N, S, E, W, NE, NW, SE, SW). **Stepping INTO a monster ATTACKS it** (melee).
  Use this to FIGHT a monster that is blocking your way, or to step around an
  obstacle one tile at a time.
- stairs_down / stairs_up: take the real '>' / '<' — you MUST already be standing
  on that stair (move_to it first; the status says when you're on a stair).
- search(times): search adjacent tiles for hidden passages (only when truly stuck
  with no monster and no reachable stair).

STRATEGY: To descend — move_to a '>' tile, then stairs_down. If move_to reports
"no path" or "blocked by '<monster>'", a monster is in the way: look at the map,
find that monster relative to you, and call move(direction) TOWARD it to attack
it (repeat until it's dead / moves), then move_to the stair again. Do NOT just
`search` when a monster is blocking — fight it. To go up, move_to a '<' then
stairs_up.

Respond with ONLY a JSON object, e.g. {"tool":"move_to","x":50,"y":16} or
{"tool":"move","direction":"SW"} or {"tool":"stairs_down"} or
{"tool":"stairs_up"} or {"tool":"search","times":10}."""


def _glm(model, messages, api_key, max_tokens=8000):
    body = json.dumps({
        "model": model, "messages": messages,
        "max_tokens": max_tokens, "temperature": 0.6,
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(f"{BASE_URL}/chat/completions", data=body, headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
        # The API's edge (Cloudflare) 403s the default Python-urllib User-Agent;
        # send a normal one so urllib behaves like curl.
        "User-Agent": "curl/8.4.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read())
    return d["choices"][0]["message"]["content"]


def _stairs(chars):
    downs = [(int(x), int(y)) for y, x in zip(*np.where(chars == ord(">")))]
    ups = [(int(x), int(y)) for y, x in zip(*np.where(chars == ord("<")))]
    return downs, ups


def _render(env, obs):
    chars = np.array(obs.chars).reshape(21, 79)
    hx, hy = int(obs.blstats[0]), int(obs.blstats[1])
    rows = ["".join(chr(c) if 32 <= c < 127 else " " for c in r) for r in chars]
    downs, ups = _stairs(chars)
    floor = env.curriculum_floor(obs)
    txt = "\n".join(r.rstrip() for r in rows if r.strip())
    on = env._engine.hero_on_stair()  # +1 down, -1 up, 0 none
    if on == 1:
        hint = "You are STANDING ON the down stair '>' — call stairs_down NOW to descend."
    elif on == -1:
        hint = "You are STANDING ON the up stair '<' — call stairs_up NOW to ascend."
    elif downs:
        hint = (f"Nearest goal: move_to a '>' tile {downs[0]} then stairs_down. "
                f"You are NOT on a stair yet.")
    elif ups:
        hint = f"No '>' here. To climb, move_to a '<' tile {ups[0]} then stairs_up."
    else:
        hint = "No stairs visible — explore with move_to / search."
    return (f"=== MAP (full vision) ===\n{txt}\n"
            f"You '@' are at ({hx},{hy}). Curriculum floor {floor}/6 "
            f"(deeper = better, then climb back).\n"
            f"HP {int(obs.blstats[10])}/{int(obs.blstats[11])} "
            f"XP-level {int(obs.blstats[18])} depth {int(obs.blstats[12])}.\n"
            f"Down stairs '>' at: {downs or 'none visible'}\n"
            f"Up stairs '<' at: {ups or 'none visible'}\n"
            f">>> {hint}"), (hx, hy), downs, ups


_DIRS = {ord('h'): (-1, 0), ord('l'): (1, 0), ord('j'): (0, 1), ord('k'): (0, -1),
         ord('y'): (-1, -1), ord('u'): (1, -1), ord('b'): (-1, 1), ord('n'): (1, 1)}
_ORTH = {(-1, 0): ord('h'), (1, 0): ord('l'), (0, 1): ord('j'), (0, -1): ord('k')}


_SIGN_NAME = {(0, -1): "N", (0, 1): "S", (1, 0): "E", (-1, 0): "W",
              (1, -1): "NE", (-1, -1): "NW", (1, 1): "SE", (-1, 1): "SW"}


def _dir_name(dx, dy):
    sx = (dx > 0) - (dx < 0)
    sy = (dy > 0) - (dy < 0)
    return _SIGN_NAME.get((sx, sy), "?")


def _is_monster(c):
    return c.isalpha() or c in "@&;:"


def _blocker_hint(chars, hero, target):
    """Name the monster blocking the route and its compass direction. Prefers a
    monster ADJACENT to the hero (the real blocker once the hero has walked to
    the frontier); else the nearest monster toward the target."""
    cx, cy = hero
    # adjacent monster (the actual doorway/corridor blocker at the frontier)
    adj = []
    for k, (dx, dy) in _DIRS.items():
        x, y = cx + dx, cy + dy
        if 0 <= x < 79 and 0 <= y < 21 and _is_monster(chr(int(chars[y, x]))):
            adj.append((abs(x - target[0]) + abs(y - target[1]), x, y,
                        chr(int(chars[y, x])), _dir_name(dx, dy)))
    if adj:
        _, mx, my, mc, dname = min(adj)
        return (f"blocked: a monster '{mc}' is right next to you ({dname}, at "
                f"({mx},{my})) on the only way to {target} — ATTACK it: "
                f"move(direction='{dname}') (repeat until it dies), then move_to {target}")
    # otherwise nearest monster overall
    best, bestd = None, 1e9
    for y in range(21):
        for x in range(79):
            if (x, y) != (cx, cy) and _is_monster(chr(int(chars[y, x]))):
                d = abs(x - cx) + abs(y - cy)
                if d < bestd:
                    bestd, best = d, (x, y, chr(int(chars[y, x])))
    if best is not None:
        mx, my, mc = best
        dn = _dir_name(mx - cx, my - cy)
        return (f"no A* path to {target}: nearest monster '{mc}' at ({mx},{my}) "
                f"is to your {dn} — head that way (move(direction='{dn}')) and "
                f"attack it to clear the route, then move_to {target}")
    return (f"no A* path from {hero} to {target}; no monster visible — the way may "
            f"need a door: try move(direction=...) toward {target} or search")


def _pos(obs):
    return int(obs.blstats[0]), int(obs.blstats[1])


def _try(env, key):
    p0 = _pos(env._engine.to_core_observation())
    obs, done, _ = env.step(int(key))
    return obs, done, (_pos(obs) != p0)


def _move_to(env, x, y, max_steps=150):
    """Adaptively walk to (x,y): re-path with A* from the CURRENT tile every
    step (a single blocked step never desyncs the route). Opens a closed door
    when one blocks an orthogonal step; decomposes a blocked diagonal into
    orthogonal moves (NetHack forbids diagonal door entry). Real moves only —
    never descends."""
    tx, ty = int(x), int(y)
    obs = env._engine.to_core_observation()
    stuck = 0
    for _ in range(max_steps):
        cx, cy = _pos(obs)
        if (cx, cy) == (tx, ty):
            return obs, False, f"reached ({tx},{ty})"
        chars = np.array(obs.chars).reshape(21, 79)
        path = a_star(chars, (cx, cy), (tx, ty))
        if not path:
            # No walkable A* route — usually a monster on the only doorway/
            # corridor. Walk to the FRONTIER (nearest reachable tile to the
            # target) so the agent ends up next to the blocker, then report it
            # actionably (which monster, which direction) for move()-to-attack.
            reach = reachable_set(chars, (cx, cy))
            frontier = min(reach, key=lambda t: abs(t[0] - tx) + abs(t[1] - ty)) \
                if reach else (cx, cy)
            if frontier == (cx, cy):
                return obs, False, _blocker_hint(chars, (cx, cy), (tx, ty))
            fpath = a_star(chars, (cx, cy), frontier)
            if not fpath:
                return obs, False, _blocker_hint(chars, (cx, cy), (tx, ty))
            path = fpath   # walk toward the frontier with the normal step logic
        key = int(path[0])
        dx, dy = _DIRS[key]
        ax, ay = cx + dx, cy + dy
        ahead = chr(int(chars[ay, ax])) if 0 <= ay < 21 and 0 <= ax < 79 else " "
        obs, done, moved = _try(env, key)
        if done:
            return obs, True, "died en route"
        if not moved:
            # Resolve the block, in priority order:
            if dx != 0 and dy != 0:
                # Diagonal block (incl. diagonally onto a door, which NetHack
                # forbids): step around it orthogonally.
                for ok in (_ORTH[(dx, 0)], _ORTH[(0, dy)]):
                    obs, done, moved = _try(env, ok)
                    if done:
                        return obs, True, "died en route"
                    if moved:
                        break
            if not moved and (dx == 0 or dy == 0) and ahead == "+":
                env.step(ord("o")); env.step(key)        # open the closed door
                obs, done, moved = _try(env, key)
                if done:
                    return obs, True, "died en route"
            if not moved and (ahead.isalpha() or ahead in "@&;:"):
                for _ in range(6):                       # attack a blocking monster
                    obs, done, moved = _try(env, key)
                    if done:
                        return obs, True, "died en route"
                    if moved:
                        break
        if moved:
            stuck = 0
            continue
        stuck += 1
        if stuck >= 3:
            return obs, False, f"stuck near ({cx},{cy}) heading to ({tx},{ty})"
    return obs, False, f"reached vicinity of ({tx},{ty})"


_NAME_DIR = {"N": ord('k'), "S": ord('j'), "E": ord('l'), "W": ord('h'),
             "NE": ord('u'), "NW": ord('y'), "SE": ord('n'), "SW": ord('b')}


def _exec(env, action):
    tool = action.get("tool")
    if tool == "move_to":
        return _move_to(env, action.get("x", 0), action.get("y", 0))
    if tool == "move":
        key = _NAME_DIR.get(str(action.get("direction", "")).upper().strip())
        if key is None:
            obs = env._engine.to_core_observation()
            return obs, False, f"bad direction {action.get('direction')!r}"
        before = _pos(env._engine.to_core_observation())
        obs, done, _ = env.step(key)
        after = _pos(obs)
        if done:
            return obs, True, "died"
        moved = after != before
        return obs, done, (f"moved {action.get('direction')}" if moved
                           else f"attacked/blocked toward {action.get('direction')} (stayed {before})")
    if tool == "stairs_down":
        obs, done, _ = env.step(ord(">"))
        return obs, done, "took '>'"
    if tool == "stairs_up":
        obs, done, _ = env.step(ord("<"))
        return obs, done, "took '<'"
    if tool == "search":
        obs = done = None
        for _ in range(int(action.get("times", 1))):
            obs, done, _ = env.step(ord("s"))
            if done:
                break
        return obs, done, "searched"
    # unknown tool: no-op step
    obs, done, _ = env.step(ord("s"))
    return obs, done, f"unknown tool {tool!r}"


def _parse(content):
    if not content:  # reasoning models can return null content if truncated
        return {"tool": "search", "times": 1}
    try:
        return json.loads(content)
    except Exception:
        i, j = content.find("{"), content.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(content[i:j + 1])
            except Exception:
                pass
    return {"tool": "search", "times": 1}


def run_voyager(*, seed, max_turns, model, api_key, verbose=True):
    env = CurriculumEngineEnv()
    obs, _ = env.reset(seeds=(seed, seed))
    deepest = env.curriculum_floor(obs)
    min_after_bottom = MAX_FLOOR
    reached_bottom = False
    timeseries = []
    last_feedback = "Begin."
    for turn in range(max_turns):
        view, _pos, _downs, _ups = _render(env, obs)
        user = f"{view}\n\nLast action result: {last_feedback}\nWhat is your next tool call?"
        try:
            content = _glm(model, [{"role": "system", "content": SYSTEM},
                                   {"role": "user", "content": user}], api_key)
        except Exception as exc:
            last_feedback = f"(LLM error: {exc})"
            content = "{}"
        action = _parse(content)
        try:
            obs, done, last_feedback = _exec(env, action)
        except Exception as exc:
            done, last_feedback = False, f"(tool error: {exc})"
        floor = env.curriculum_floor(obs)
        if floor > 0:
            deepest = max(deepest, floor)
        bottomed = deepest >= MAX_FLOOR
        if bottomed:
            reached_bottom = True
            if floor > 0:
                min_after_bottom = min(min_after_bottom, floor)
        climbed = (deepest - min_after_bottom) if reached_bottom else 0
        timeseries.append({"turn": turn + 1, "tool": action.get("tool"),
                           "floor": floor, "deepest_floor": deepest,
                           "climbed_back": climbed})
        if verbose:
            print(f"[turn {turn+1:3d}] {str(action.get('tool')):10s} "
                  f"floor={floor} deepest={deepest}/6 climbed_back={climbed}", flush=True)
        if done:
            last_feedback = "(You died — episode ended.)"
            break
    return {"algo": "voyager", "seed": seed, "model": model,
            "deepest_floor": deepest,
            "climbed_back": (deepest - min_after_bottom) if reached_bottom else 0,
            "reached_bottom": reached_bottom, "turns": len(timeseries),
            "timeseries": timeseries}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[19])
    ap.add_argument("--max-turns", type=int, default=60)
    ap.add_argument("--model", default="z-ai/glm-5.2")
    ap.add_argument("--out", default="outputs/curriculum_experiments/voyager")
    args = ap.parse_args()
    api_key = os.environ.get("PI_API_KEY") or os.environ.get("REFINER_API_KEY")
    if not api_key:
        raise SystemExit("set PI_API_KEY (the Prime api_key from ~/.prime/config.json)")
    out = pathlib.Path(args.out); out.mkdir(parents=True, exist_ok=True)
    summary = []
    for seed in args.seeds:
        print(f"=== Voyager curriculum: seed {seed} ({args.model}) ===")
        res = run_voyager(seed=seed, max_turns=args.max_turns, model=args.model, api_key=api_key)
        (out / f"voyager_seed{seed}.json").write_text(json.dumps(res, indent=2))
        summary.append({k: res[k] for k in
                        ("seed", "deepest_floor", "climbed_back", "reached_bottom")})
        print(f"  -> deepest_floor={res['deepest_floor']}/6 "
              f"climbed_back={res['climbed_back']} reached_bottom={res['reached_bottom']}")
    (out / "voyager_summary.json").write_text(json.dumps(summary, indent=2))
    print("summary:", json.dumps(summary))


if __name__ == "__main__":
    main()
