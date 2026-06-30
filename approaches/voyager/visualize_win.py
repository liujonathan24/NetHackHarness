"""Visualize a real scripted climb tile-by-tile: an animated GIF + a key-moments
montage of the @ pathing to the up-stair '<' and the dungeon floor ticking down.

Deterministic (no LLM), so it exactly reproduces a row from the scripted sweep.
Showcase: seed 7 from floor 4 climbs Gehennom-48 -> DoD-3 -> DoD-2 (crossing the
internal cross-branch jump-up), then gets stuck — a genuine multi-floor win AND
its failure mode in one episode.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.animation as animation
import matplotlib.pyplot as plt
import numpy as np

_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "environments" / "nethack"))
sys.path.insert(0, str(_ROOT / "approaches" / "voyager"))

import curriculum_voyager as cv  # noqa: E402
import reverse_curriculum_sweep as rc  # noqa: E402
from nethack_core.curriculum_engine_env import CurriculumEngineEnv  # noqa: E402

FLOOR_NAME = {1: "DoD 1", 2: "DoD 2", 3: "DoD 3",
              4: "Gehennom 48", 5: "Gehennom 49", 6: "Gehennom 50"}


def _frame(env, obs, label):
    chars = np.array(obs.chars).reshape(21, 79).copy()
    hx, hy = cv._pos(obs)
    return {"chars": chars, "hx": hx, "hy": hy,
            "floor": env.curriculum_floor(obs),
            "depth": int(obs.blstats[12]), "label": label}


def _capture_nav(env, frames, x, y, max_steps=200):
    """nav_to, but append a frame after every engine step so the GIF shows the @
    walking tile-by-tile. Returns (obs, reason) where reason in
    {'reached','monster','nopath','died'} — mirrors rc.nav_to's stop conditions."""
    tx, ty = int(x), int(y)
    obs = env._engine.to_core_observation()
    for _ in range(max_steps):
        cx, cy = cv._pos(obs)
        if (cx, cy) == (tx, ty):
            return obs, "reached"
        glyphs = np.array(obs.glyphs).reshape(21, 79)
        chars = np.array(obs.chars).reshape(21, 79)
        wv = rc._walk_open_doors(glyphs)
        path = rc._bfs_path(wv, rc._door_mask(glyphs), (cx, cy), (tx, ty))
        if not path:
            return obs, "nopath"
        key = path[0]
        dx, dy = cv._DIRS[key]
        nx, ny = cx + dx, cy + dy
        if cv._is_monster(chr(int(chars[ny, nx]))) and chr(int(chars[ny, nx])) != "@":
            return obs, "monster"
        if rc._is_closed_door(glyphs, nx, ny):
            env.step(ord("o")); obs, done, _ = env.step(key)
            frames.append(_frame(env, obs, "open door"))
            if done:
                return obs, "died"
            continue
        obs, done, moved = cv._try(env, key)
        frames.append(_frame(env, obs, f"navigate toward '<' on {FLOOR_NAME.get(env.curriculum_floor(obs),'?')}"))
        if done:
            return obs, "died"
        if not moved:
            return obs, "nopath"
    return obs, "nopath"


def _attack_adjacent(env, obs, frames):
    chars = np.array(obs.chars).reshape(21, 79)
    cx, cy = cv._pos(obs)
    for key, (dx, dy) in cv._DIRS.items():
        x, y = cx + dx, cy + dy
        if 0 <= x < 79 and 0 <= y < 21 and cv._is_monster(chr(int(chars[y, x]))) \
                and chr(int(chars[y, x])) != "@":
            o, done, _ = env.step(key)
            frames.append(_frame(env, o, "fight blocking monster"))
            return o, done, True
    return obs, False, False


def capture_climb(seed, start_floor, max_iters=80):
    """Faithful frame-capturing replica of scripted_nav_reachability.scripted_climb
    (greedy climb + monster fights + stuck-retry)."""
    env = CurriculumEngineEnv(); obs, _ = env.reset(seeds=(seed, seed))
    obs = rc.construct_start(env, obs, start_floor)
    frames = [_frame(env, obs, f"START at {FLOOR_NAME[start_floor]}")]
    f_cur = env.curriculum_floor(obs)
    stuck = 0
    for _ in range(max_iters):
        if env.curriculum_floor(obs) == 1:
            break
        on = env._engine.hero_on_stair()
        if on == -1:
            obs, done, _ = cv._exec(env, {"tool": "stairs_up"})
            frames.append(_frame(env, obs, f"take '<'  →  now {FLOOR_NAME.get(env.curriculum_floor(obs),'?')}"))
        else:
            chars = np.array(obs.chars).reshape(21, 79)
            _d, ups = cv._stairs(chars)
            if ups:
                obs, reason = _capture_nav(env, frames, *min(
                    ups, key=lambda p: abs(p[0]-cv._pos(obs)[0])+abs(p[1]-cv._pos(obs)[1])))
                if env._engine.hero_on_stair() == -1:
                    obs, done, _ = cv._exec(env, {"tool": "stairs_up"})
                    frames.append(_frame(env, obs, f"take '<'  →  now {FLOOR_NAME.get(env.curriculum_floor(obs),'?')}"))
                elif reason == "monster":
                    obs, done, acted = _attack_adjacent(env, obs, frames)
                    if not acted:        # blocker not orth-adjacent to hero
                        stuck += 1
                else:
                    stuck += 1
            else:
                for _ in range(8):
                    obs, done, _ = env.step(ord("s"))
                frames.append(_frame(env, obs, "search for hidden passage"))
                stuck += 1
        nf = env.curriculum_floor(obs)
        if 0 < nf < f_cur:
            stuck = 0; f_cur = nf
        if stuck >= 5:
            frames.append(_frame(env, obs, f"STUCK on {FLOOR_NAME.get(nf,'?')} — can't reach '<'"))
            break
    return frames


def _draw(ax, fr):
    ax.clear(); ax.axis("off")
    rows = ["".join(chr(c) if 32 <= c < 127 else " " for c in r) for r in fr["chars"]]
    # trim blank rows for a tighter view
    nonblank = [i for i, r in enumerate(rows) if r.strip()]
    if nonblank:
        rows = rows[max(0, nonblank[0]-1):nonblank[-1]+2]
    ax.text(0.01, 0.98, "\n".join(rows), family="monospace", fontsize=7.5,
            va="top", ha="left", transform=ax.transAxes)
    # highlight hero @ (red) and up-stair < (green) with markers in axes coords
    color = {"START": "tab:blue"}
    ax.set_title(f"floor {fr['floor']}/6  ({FLOOR_NAME.get(fr['floor'],'?')}, dlvl {fr['depth']})   |   {fr['label']}",
                 fontsize=10, color=("green" if "take '<'" in fr["label"] else
                                     "darkred" if "STUCK" in fr["label"] else "black"))


def make_gif(frames, path, fps=4):
    fig, ax = plt.subplots(figsize=(11, 4.2))
    def upd(i):
        _draw(ax, frames[i]); return []
    anim = animation.FuncAnimation(fig, upd, frames=len(frames), interval=1000 // fps)
    anim.save(path, writer=animation.PillowWriter(fps=fps))
    plt.close(fig)


def make_montage(frames, path):
    # key moments: start, every floor-change ("take '<'"), and the final frame
    keys = [0] + [i for i, f in enumerate(frames) if "take '<'" in f["label"] or "STUCK" in f["label"]]
    keys = sorted(set(keys + [len(frames) - 1]))
    n = len(keys)
    fig, axes = plt.subplots(n, 1, figsize=(11, 2.6 * n))
    if n == 1:
        axes = [axes]
    for ax, k in zip(axes, keys):
        _draw(ax, frames[k])
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--floor", type=int, default=4)
    ap.add_argument("--out", default="outputs/curriculum_experiments/reverse_curriculum")
    args = ap.parse_args()
    out = pathlib.Path(args.out); out.mkdir(parents=True, exist_ok=True)
    frames = capture_climb(args.seed, args.floor)
    tag = f"win_seed{args.seed}_f{args.floor}"
    print(f"{tag}: {len(frames)} frames; floors visited: "
          f"{[f['floor'] for f in frames if f['label'].startswith(('START','take'))]}")
    make_gif(frames, out / f"{tag}.gif")
    make_montage(frames, out / f"{tag}_montage.png")
    print(f"wrote {out}/{tag}.gif and {tag}_montage.png")


if __name__ == "__main__":
    main()
