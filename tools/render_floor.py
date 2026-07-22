"""Render generated NetHack floors at varying map-generation knobs to a PNG.

Headless-friendly way to "see the floor layout change" as you turn the
generation knobs (Pillar 2). Drives the fork engine via EngineEnv with
tune-at-start so the *starting* level is generated with the given knobs.

    python tools/render_floor.py --knob room_density --values 1.0 0.3 0.1 0.05
    python tools/render_floor.py --knob room_density --values 1.0 0.1 --seed 7 -o /tmp/floors.png
"""

from __future__ import annotations

import argparse
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "environments" / "nethack"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from nethack_core import EngineEnv  # noqa: E402

_COLORS = {
    "@": (255, 220, 0), ">": (0, 220, 220), "<": (0, 220, 220),
    "#": (120, 120, 120), ".": (70, 70, 80), "|": (200, 200, 200),
    "-": (200, 200, 200), "+": (0, 200, 0), "f": (220, 0, 220), "d": (220, 0, 220),
    "$": (240, 220, 0),
}


def _floor(knob: str, value: float, seed: int):
    env = EngineEnv()
    obs, _ = env.reset(seeds=(seed, seed), tune={knob: value, "reveal_map": 1.0})
    for _ in range(3):
        obs, _, _ = env.step(ord("."))
    rows = ["".join(chr(int(c)) if 32 <= int(c) < 127 else " " for c in r) for r in obs.chars]
    floors = sum(r.count(".") for r in rows)
    env.close()
    return rows, floors


def _font(size: int):
    for p in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
        "DejaVuSansMono.ttf",
    ):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--knob", default="room_density")
    ap.add_argument("--values", type=float, nargs="+", default=[1.0, 0.3, 0.1, 0.05])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("-o", "--out", default=str(_ROOT / "videos" / "floor_density_demo.png"))
    args = ap.parse_args()

    panels = [(v, *_floor(args.knob, v, args.seed)) for v in args.values]

    font = _font(13)
    cw, ch, title_h = 8, 15, 24
    width = 79 * cw + 20
    panel_h = 21 * ch + title_h
    img = Image.new("RGB", (width, panel_h * len(panels) + 10), (12, 12, 16))
    dr = ImageDraw.Draw(img)
    y = 5
    for v, rows, n in panels:
        dr.text((10, y), f"{args.knob} = {v}    ({n} floor tiles, seed {args.seed})",
                fill=(230, 230, 120), font=font)
        y0 = y + title_h
        for ri, row in enumerate(rows):
            for ci, chx in enumerate(row):
                if chx != " ":
                    dr.text((10 + ci * cw, y0 + ri * ch), chx,
                            fill=_COLORS.get(chx, (180, 180, 180)), font=font)
        y += panel_h
    pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out)
    print(f"wrote {args.out} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
