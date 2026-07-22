"""Generate animated GIFs demonstrating each difficulty/generation knob's effect.

Each GIF drives the fork engine (EngineEnv) and renders the structured map
(chars+colors) + a caption + status line into frames, then writes an animated
GIF. Used to *verify* that a knob actually changes the game, not just that it is
settable.

    python tools/knob_gifs.py room_density
    python tools/knob_gifs.py all
"""

from __future__ import annotations

import argparse
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "environments" / "nethack"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from nethack_core import EngineEnv  # noqa: E402

OUT = _ROOT / "videos"
_PALETTE = ["#1a1a1a", "#c44", "#4b4", "#b83", "#46c", "#b5b", "#5bb", "#bbb",
            "#666", "#f66", "#6f6", "#fd5", "#6af", "#f6f", "#6ff", "#fff"]
_CW, _CH, _CAP_H, _STAT_H = 8, 14, 24, 20


def _font(sz):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
              "/usr/share/fonts/dejavu/DejaVuSansMono.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except OSError:
            continue
    return ImageFont.load_default()


_F = _font(13)
_FB = _font(14)


def _obs_rows(obs):
    rows = ["".join(chr(int(c)) if 32 <= int(c) < 127 else " " for c in r) for r in obs.chars]
    colors = [[int(c) for c in r] for r in obs.colors]
    return rows, colors


def _status(obs):
    b = [int(x) for x in obs.blstats]
    return f"HP {b[10]}/{b[11]}  AC {b[16]}  Dlvl {b[12]}  ${b[13]}  hunger~{int(obs.message[0]) and ''}"


def frame(rows, colors, caption, status_text="", hl=(255, 230, 120)):
    w = 79 * _CW + 16
    h = _CAP_H + 21 * _CH + _STAT_H
    img = Image.new("RGB", (w, h), (12, 12, 16))
    d = ImageDraw.Draw(img)
    d.text((8, 4), caption, fill=hl, font=_FB)
    y0 = _CAP_H
    for ri, row in enumerate(rows):
        for ci, ch in enumerate(row):
            if ch == " ":
                continue
            c = colors[ri][ci]
            col = _PALETTE[c] if 0 <= c < 16 else "#bbb"
            d.text((8 + ci * _CW, y0 + ri * _CH), ch, fill=col, font=_F)
    if status_text:
        d.text((8, _CAP_H + 21 * _CH), status_text, fill=(200, 200, 210), font=_F)
    return img


def save_gif(name, frames, duration=700):
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"gif_{name}.gif"
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=duration,
                   loop=0, optimize=True)
    print(f"wrote {out} ({len(frames)} frames)")
    return out


# --------------------------------------------------------------------------
# Per-knob GIF builders
# --------------------------------------------------------------------------

def _regen(env, seed, **tune):
    obs, _ = env.reset(seeds=(seed, seed), tune={"reveal_map": 1.0, **tune})
    for _ in range(3):
        obs, _, _ = env.step(ord("."))
    return obs


def gif_room_density(seed=42):
    env = EngineEnv()
    frames = []
    # room_density is thresholded: the floor is unchanged from 1.0 down to ~0.2,
    # then thins out sharply. Pick values that each cross a threshold so every
    # frame visibly differs (1.0->276, 0.15->248, 0.1->163, 0.05->54, 0.02->39
    # floor tiles on this seed) instead of five identical "full floor" frames.
    for d in (1.0, 0.15, 0.1, 0.05, 0.02):
        obs = _regen(env, seed, room_density=d)
        rows, colors = _obs_rows(obs)
        floors = sum(r.count(".") for r in rows)
        frames.append(frame(rows, colors, f"room_density = {d:<5}   ({floors} floor tiles, seed {seed})"))
    env.close()
    # ping-pong so the loop reads naturally
    return save_gif("room_density", frames + frames[-2:0:-1], duration=650)


def gif_reveal_map(seed=42):
    """fog vs full reveal: explore with fog, then reveal_map=1 pops the floor in."""
    env = EngineEnv()
    obs, _ = env.reset(seeds=(seed, seed), tune={"reveal_map": 0.0})
    frames = []
    for i, a in enumerate([ord("j"), ord("j"), ord("l"), ord("l")]):
        obs, _, _ = env.step(a)
        rows, colors = _obs_rows(obs)
        n = sum(r.count(".") + r.count("#") for r in rows)
        frames.append(frame(rows, colors, f"reveal_map = 0  (fog: only what you've seen, {n} cells)"))
    env.set_tune(reveal_map=1.0)
    obs, _, _ = env.step(ord("."))
    rows, colors = _obs_rows(obs)
    n = sum(r.count(".") + r.count("#") for r in rows)
    full = frame(rows, colors, f"reveal_map = 1  (whole floor revealed, {n} cells)", hl=(120, 230, 120))
    env.close()
    return save_gif("reveal_map", frames + [full] * 3 + frames[::-1], duration=600)


def _bar(d, x, y, w, h, frac, color, label, value):
    frac = max(0.0, min(1.0, frac))
    d.rectangle([x, y, x + w, y + h], outline=(90, 90, 100))
    d.rectangle([x + 1, y + 1, x + 1 + int((w - 2) * frac), y + h - 1], fill=color)
    d.text((x + w + 10, y + h // 2 - 7), f"{label}  {value}", fill=(220, 220, 220), font=_F)


def gif_hunger(seed=42, nsteps=120):
    """Hunger (u.uhunger) depletes faster at higher hunger_rate_scale.

    Two synchronized runs (scale 1.0 vs 3.0) stepping the same actions; bars
    show the nutrition counter draining 3x faster on the bottom.
    """
    acts = [ord("j"), ord("l"), ord("k"), ord("h")]
    e1 = EngineEnv(); e1.reset(seeds=(seed, seed), tune={"hunger_rate_scale": 1.0})
    e3 = EngineEnv(); e3.reset(seeds=(seed, seed), tune={"hunger_rate_scale": 3.0})
    start = int(e1.engine._internal[7])
    frames = []
    for i in range(0, nsteps, 4):
        for k in range(4):
            e1.step(acts[(i + k) % 4]); e3.step(acts[(i + k) % 4])
        h1 = int(e1.engine._internal[7]); h3 = int(e3.engine._internal[7])
        img = Image.new("RGB", (560, 150), (12, 12, 16)); d = ImageDraw.Draw(img)
        d.text((10, 8), f"hunger_rate_scale — nutrition counter after {i + 4} steps (seed {seed})",
                fill=(255, 230, 120), font=_FB)
        _bar(d, 14, 50, 360, 22, h1 / start, (90, 200, 90), "scale 1.0", h1)
        _bar(d, 14, 95, 360, 22, h3 / start, (220, 120, 60), "scale 3.0", h3)
        frames.append(img)
    e1.close(); e3.close()
    return save_gif("hunger_rate_scale", frames, duration=180)


def gif_mob_spawn(seed=42):
    """Empty floor -> swarm: more initial monsters at higher mob_spawn."""
    env = EngineEnv()
    frames = []
    for v in (0.0, 1.0, 2.0, 3.0):
        obs = _regen(env, seed, mob_spawn=v)
        rows, colors = _obs_rows(obs)
        # monsters/pets are the alphabetic glyphs on the map; minus the @ hero.
        nmon = sum(sum(ch.isalpha() for ch in r) for r in rows) - 1
        frames.append(frame(rows, colors,
                            f"mob_spawn = {v:<4}   ({nmon} monsters on the floor, seed {seed})"))
    env.close()
    return save_gif("mob_spawn", frames + frames[-2:0:-1], duration=750)


def gif_room_size(seed=42):
    """Cramped warrens vs cavernous halls: room_size scales each room's
    dimensions (the floor-tile count wobbles because the generator fits a
    different number of rooms, but the room SHAPES change clearly)."""
    env = EngineEnv()
    frames = []
    for v in (0.25, 0.5, 1.0, 2.0, 3.0):
        obs = _regen(env, seed, room_size=v)
        rows, colors = _obs_rows(obs)
        floors = sum(r.count(".") for r in rows)
        frames.append(frame(rows, colors,
                            f"room_size = {v:<4}   ({floors} floor tiles, seed {seed})"))
    env.close()
    return save_gif("room_size", frames + frames[-2:0:-1], duration=650)


def gif_backstep(seed=42, fwd=5):
    """Play forward, then Backspace-undo back to the start. Uses the exact
    snapshot/restore mechanism the live Undo button does: snapshot before each
    step, then restore them in reverse (a ctrl-R redraw renders each reverted
    frame), so the @ walks out and retraces its steps."""
    env = EngineEnv()
    env.reset(seeds=(seed, seed))
    for _ in range(2):           # drain the welcome --More-- into live play
        env.step(ord("."))
    frames, snaps = [], []
    obs = env.engine.to_core_observation()
    rows, colors = _obs_rows(obs)
    frames.append(frame(rows, colors, "play forward — start"))
    for i in range(fwd):         # forward: snapshot, step right, capture
        snaps.append(env.snapshot())
        obs, _, _ = env.step(ord("l"))
        rows, colors = _obs_rows(obs)
        frames.append(frame(rows, colors, f"play forward — step {i + 1}"))
    for i in range(len(snaps) - 1, -1, -1):   # backward: restore + ctrl-R redraw
        env.restore(snaps[i])
        obs, _, _ = env.step(18)
        rows, colors = _obs_rows(obs)
        frames.append(frame(rows, colors,
                            f"Backspace = undo  —  back to step {i}", hl=(120, 230, 120)))
    for s in snaps:
        env.free_snapshot(s)
    env.close()
    return save_gif("backstep", frames, duration=480)


_BUILDERS = {
    "room_density": gif_room_density,
    "room_size": gif_room_size,
    "reveal_map": gif_reveal_map,
    "mob_spawn": gif_mob_spawn,
    "backstep": gif_backstep,
    # hunger_rate_scale (gif_hunger) kept as a function but dropped from the
    # gallery — the two-bar nutrition demo wasn't compelling.
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("knob", help="knob name or 'all'")
    args = ap.parse_args()
    names = list(_BUILDERS) if args.knob == "all" else [args.knob]
    for n in names:
        if n not in _BUILDERS:
            print(f"no GIF builder for {n!r}; have: {list(_BUILDERS)}")
            continue
        _BUILDERS[n]()


if __name__ == "__main__":
    main()
