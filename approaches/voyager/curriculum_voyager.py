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
from nethack_core.glyphs import (  # noqa: E402
    CMAP_CLOSED_DOOR_INDICES, GLYPH_CMAP_OFF, cmap_clean_char_lut, glyph_is_cmap,
    glyph_is_monster, glyph_is_object,
)
from nethack_harness.navigation.pathfinding import a_star, reachable_set  # noqa: E402

_CMAP_LUT = cmap_clean_char_lut()

BASE_URL = "https://api.pinference.ai/api/v1"
MAX_FLOOR = 6

SYSTEM = """You are playing NetHack as a female neutral Valkyrie with FULL VISION
(the whole level is visible). GOAL: descend as DEEP as possible, then climb back
UP. Taking the down stairs on dungeon level 3 jumps you deep into the game
automatically; keep going down to the bottom, then turn around and climb all the
way back up.

Tools (real NetHack primitives — YOU decide how to use them):
- move_to(x, y): walk to tile (x,y) along VISIBLY-OPEN terrain (floor, corridor,
  open doorway, stairs). It is plain navigation: it does NOT open/kick doors,
  attack monsters, or push through anything. If the way is blocked it STOPS and
  tells you what's adjacent (a closed door '+', a monster, etc.) and which way
  the target is. Then it's YOUR job to act.
- move(direction): one real step (N,S,E,W,NE,NW,SE,SW). Stepping into a monster
  ATTACKS it; stepping into your pet swaps places.
- open(direction): open an adjacent closed door '+'.
- kick(direction): kick an adjacent door (use when open says it's LOCKED).
- search(times): search adjacent tiles for hidden passages/doors.
- stairs_down / stairs_up: take the real '>' / '<' (you must be standing on it).

STRATEGY: To descend — move_to a visible '>', then stairs_down. When move_to
stops "blocked", read what it reports and decide: a closed door -> open(dir)
(if it says locked -> kick(dir)); a monster -> move(dir) to attack it until it's
gone; nothing adjacent and no route -> search for a hidden passage or pick a
different tile to move_to. Then continue toward the stair. To go up: move_to a
'<', then stairs_up.

Respond with ONLY a JSON object, e.g. {"tool":"move_to","x":50,"y":16},
{"tool":"move","direction":"SW"}, {"tool":"open","direction":"W"},
{"tool":"kick","direction":"W"}, {"tool":"search","times":10},
{"tool":"stairs_down"}, {"tool":"stairs_up"}."""


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
    """Factual report of what is adjacent and in the way (closed doors '+' and
    monsters), with directions, plus the rough direction to the target. It does
    NOT prescribe an action — the agent decides whether to open/kick a door,
    attack a monster, search, or go around."""
    cx, cy = hero
    doors, mons = [], []
    for _k, (dx, dy) in _DIRS.items():
        x, y = cx + dx, cy + dy
        if not (0 <= x < 79 and 0 <= y < 21):
            continue
        c = chr(int(chars[y, x]))
        if c == "+":
            doors.append(_dir_name(dx, dy))
        elif _is_monster(c):
            mons.append(f"'{c}' {_dir_name(dx, dy)}")
    tgt_dir = _dir_name(target[0] - cx, target[1] - cy)
    parts = [f"no open path to {target} (it's roughly {tgt_dir} of you)."]
    if doors:
        parts.append(f"Adjacent closed door(s): {', '.join(doors)}.")
    if mons:
        parts.append(f"Adjacent monster(s): {', '.join(mons)}.")
    if not doors and not mons:
        parts.append("No adjacent door/monster — the route may need exploration "
                     "(a hidden passage) or you must go around.")
    return " ".join(parts)


def _walkview(glyphs):
    """Build a clean walkability map from GLYPHS (unambiguous), not chars.

    Chars can't tell an open door/doorway (renders as '|'/'-' — same as a wall)
    from a real wall, so A* over chars wrongly refuses to path through doors.
    Glyphs distinguish them: the cmap LUT maps open doors / doorways / corridors
    / floor / stairs to walkable, and closed doors / walls / rock to blocked.
    Monsters and items are made walkable too (stepping in swaps-with-pet /
    attacks-hostile / picks-up-item), so A* routes through them."""
    g = np.asarray(glyphs).astype(np.int64)
    v = np.full(g.shape, ord("|"), dtype=np.uint8)   # default: blocked
    cm = glyph_is_cmap(g)
    idx = np.clip(g - GLYPH_CMAP_OFF, 0, len(_CMAP_LUT) - 1)
    v[cm] = _CMAP_LUT[idx[cm]]
    # Items lying on the floor are walkable. Closed doors and monsters are NOT —
    # walking there requires a deliberate action (open/kick a door, attack a
    # monster), which is the agent's decision, not move_to's.
    v[glyph_is_object(g)] = ord(".")
    return v


def _pos(obs):
    return int(obs.blstats[0]), int(obs.blstats[1])


def _try(env, key):
    p0 = _pos(env._engine.to_core_observation())
    obs, done, _ = env.step(int(key))
    return obs, done, (_pos(obs) != p0)


def _move_to(env, x, y, max_steps=80):
    """GENERIC navigation only: A* over visibly-open terrain (floor, corridor,
    OPEN door, doorway, stairs, items) and walk it. It does NOT open/kick doors,
    attack monsters, or push through blockers — those are deliberate actions the
    AGENT must choose via the move/open/kick/search primitives. If the path is
    blocked (closed door, monster, or no open route), it stops and reports what
    is in the way, factually, for the agent to decide. Re-paths each step so a
    monster wandering onto the route just reroutes; never descends."""
    tx, ty = int(x), int(y)
    obs = env._engine.to_core_observation()
    for _ in range(max_steps):
        cx, cy = _pos(obs)
        if (cx, cy) == (tx, ty):
            return obs, False, f"reached ({tx},{ty})"
        chars = np.array(obs.chars).reshape(21, 79)
        wv = _walkview(np.array(obs.glyphs).reshape(21, 79))
        path = a_star(wv, (cx, cy), (tx, ty))
        if not path:
            # The exact target isn't reachable over open terrain (a closed door
            # / monster / unexplored gap is in the way). Walk as far toward it as
            # open ground allows, then stop and report — the agent acts (open/
            # kick/fight/search). This is plain navigation, not obstacle-solving.
            reach = reachable_set(wv, (cx, cy))
            frontier = min(reach, key=lambda t: abs(t[0] - tx) + abs(t[1] - ty)) \
                if reach else (cx, cy)
            if frontier == (cx, cy):
                return obs, False, _blocker_hint(chars, (cx, cy), (tx, ty))
            path = a_star(wv, (cx, cy), frontier)
            if not path:
                return obs, False, _blocker_hint(chars, (cx, cy), (tx, ty))
        obs, done, moved = _try(env, int(path[0]))
        if done:
            return obs, True, "died en route"
        if not moved:
            # A tile that was open got blocked (a monster stepped in). Stop and
            # report — the agent decides what to do.
            return obs, False, _blocker_hint(chars, (cx, cy), (tx, ty))
    return obs, False, f"still en route to ({tx},{ty})"


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
    if tool in ("open", "kick"):
        key = _NAME_DIR.get(str(action.get("direction", "")).upper().strip())
        if key is None:
            obs = env._engine.to_core_observation()
            return obs, False, f"bad direction {action.get('direction')!r}"
        cmd = ord("o") if tool == "open" else 4   # 'o'pen / ^D kick
        env.step(cmd)
        obs, done, _ = env.step(key)              # apply to the given direction
        msg = bytes(obs.message).split(b"\x00")[0].decode("latin1")
        return obs, bool(done), f"{tool} {action.get('direction')}: {msg[:50]}"
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
