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
from nethack_harness.navigation.pathfinding import a_star  # noqa: E402

BASE_URL = "https://api.pinference.ai/api/v1"
MAX_FLOOR = 6

SYSTEM = """You are playing NetHack as a female neutral Valkyrie with FULL VISION
(the whole level is visible). GOAL: descend as DEEP as possible, then climb back
UP. Taking the down stairs on dungeon level 3 jumps you deep into the game
automatically; keep going down to the bottom, then turn around and climb all the
way back up.

You have ONLY these tools (no auto-descend, no "descend" skill):
- move_to(x, y): walk to tile (x,y) over the visible map.
- stairs_down: take the '>' down stairs. You MUST be standing on a '>' first
  (move_to it).
- stairs_up: take the '<' up stairs. You MUST be standing on a '<' first.
- search(times): search adjacent tiles for hidden passages (when stuck).

To go down: move_to a '>' tile, then call stairs_down. To go up: move_to a '<'
tile, then stairs_up. The map lists every visible '>' and '<' with coordinates.

Respond with ONLY a JSON object, e.g. {"tool":"move_to","x":50,"y":16} or
{"tool":"stairs_down"} or {"tool":"stairs_up"} or {"tool":"search","times":10}."""


def _glm(model, messages, api_key, max_tokens=3000):
    body = json.dumps({
        "model": model, "messages": messages,
        "max_tokens": max_tokens, "temperature": 0.6,
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(f"{BASE_URL}/chat/completions", data=body, headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
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
    return (f"=== MAP (full vision) ===\n{txt}\n"
            f"You '@' are at ({hx},{hy}). Curriculum floor {floor}/6 "
            f"(deeper = better, then climb back).\n"
            f"HP {int(obs.blstats[10])}/{int(obs.blstats[11])} "
            f"XP-level {int(obs.blstats[18])} depth {int(obs.blstats[12])}.\n"
            f"Down stairs '>' at: {downs or 'none visible'}\n"
            f"Up stairs '<' at: {ups or 'none visible'}"), (hx, hy), downs, ups


def _move_to(env, x, y):
    obs = env._engine.to_core_observation()
    chars = np.array(obs.chars).reshape(21, 79)
    start = (int(obs.blstats[0]), int(obs.blstats[1]))
    path = a_star(chars, start, (int(x), int(y)))
    if not path:
        return obs, False, "no path"
    done = False
    for key in path:
        obs, done, _ = env.step(int(key))
        if done:
            break
    return obs, done, f"walked {len(path)} steps toward ({x},{y})"


def _exec(env, action):
    tool = action.get("tool")
    if tool == "move_to":
        return _move_to(env, action.get("x", 0), action.get("y", 0))
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
                  f"floor={floor} deepest={deepest}/6 climbed_back={climbed}")
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
