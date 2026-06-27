"""Pillow-only GIF renderer for env-side trace NDJSON (no matplotlib needed).

Reads the per-turn trace the harness writes when trace_dir is set (each line:
raw_grid [24 tty rows] + curriculum_floor + status + tool_calls) and renders an
animated GIF of the ASCII map with a header (turn / floor / DLvl / HP / action).

Usage:
    python tools/gif_from_trace.py --ndjson <trace.ndjson> --out videos/x.gif [--fps 4]
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# Monospace cell size + palette (terminal-ish).
CW, CH = 9, 18          # character cell width/height (px)
COLS, ROWS = 80, 24     # tty dimensions
PAD = 8
HEADER_H = 26
BG = (12, 12, 18)
FG = (210, 210, 210)
HDR = (250, 230, 120)
# Glyph highlights so the eye can track the hero + stairs.
HL = {"@": (90, 200, 255), ">": (120, 255, 120), "<": (255, 140, 140)}


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)   # Pillow >=10: scalable default
    except TypeError:
        return ImageFont.load_default()


def load_ndjson(path: Path) -> list[dict]:
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def _grid(rec: dict) -> list[str]:
    rg = rec.get("raw_grid")
    if isinstance(rg, list):
        return [str(r) for r in rg][:ROWS]
    msg = rec.get("rendered_user_message") or ""
    return msg.splitlines()[:ROWS]


def _header(rec: dict) -> str:
    st = rec.get("status") or {}
    tcs = rec.get("tool_calls") or []
    act = ""
    if tcs:
        nm = tcs[0].get("name")
        ar = tcs[0].get("arguments")
        act = f"{nm}{ar if ar and ar != '{}' else ''}"
    return (f"turn {rec.get('turn','?')}  floor {rec.get('curriculum_floor','?')}"
            f"  DLvl {rec.get('dlvl','?')}  HP {st.get('hitpoints','?')}/"
            f"{st.get('max_hitpoints','?')}   action: {act}")[:96]


def render(frames: list[dict], out: Path, label: str, fps: int) -> None:
    fnt = _font(14)
    hfnt = _font(15)
    W = COLS * CW + 2 * PAD
    H = HEADER_H + ROWS * CH + 2 * PAD + 22
    imgs = []
    for rec in frames:
        im = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(im)
        d.text((PAD, 4), _header(rec), font=hfnt, fill=HDR)
        rows = _grid(rec)
        y0 = HEADER_H + PAD
        for r, row in enumerate(rows):
            y = y0 + r * CH
            for c, ch in enumerate(row[:COLS]):
                if ch == " ":
                    continue
                d.text((PAD + c * CW, y), ch, font=fnt, fill=HL.get(ch, FG))
        d.text((PAD, H - 20), label[:110], font=fnt, fill=(140, 140, 160))
        imgs.append(im)
    if not imgs:
        raise SystemExit("no frames")
    dur = int(1000 / max(1, fps))
    # Hold the final frame longer so the end state is readable.
    durations = [dur] * (len(imgs) - 1) + [dur * 6]
    imgs[0].save(out, save_all=True, append_images=imgs[1:], duration=durations,
                 loop=0, optimize=True)
    print(f"wrote {out}  ({len(imgs)} frames, {W}x{H})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ndjson", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--fps", type=int, default=4)
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    frames = load_ndjson(a.ndjson)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    render(frames, a.out, a.label or a.ndjson.name, a.fps)


if __name__ == "__main__":
    main()
