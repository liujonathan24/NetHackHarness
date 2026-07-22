"""Render descent + ascent GIFs of the curriculum dungeon traversal.

Proves the curriculum works visually:
  * descent: DoD 1->2->3, then the JUMP to Gehennom 48 with the stat upgrade,
    then 48->49->50.
  * ascent: Gehennom 50->49->48, the JUMP back to DoD 3, then 3->2->1, then the
    JUMP into the Elemental Planes (Earth->Air->Fire->Water->Astral).

Each frame is the full revealed map (full vision) + a caption naming the
dungeon/level and the hero's XP level, HP and Strength, so the level and stat
increase on the deep jump are visible.

    python tools/curriculum_gifs.py            # both GIFs, default seed 19
    python tools/curriculum_gifs.py --seed 19
"""
from __future__ import annotations

import argparse
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "environments" / "nethack"))
sys.path.insert(0, str(_ROOT / "tools"))

from nethack_core import MiscDirection  # noqa: E402
from nethack_core import CurriculumEnv  # noqa: E402
from nethack_core import BLSTATS_IDX  # noqa: E402
from knob_gifs import _obs_rows, frame, save_gif  # noqa: E402

DOWN = int(MiscDirection.DOWN)
UP = int(MiscDirection.UP)


def _strength_str(obs) -> str:
    """Render strength the NetHack way (18/03, 18/**, or plain)."""
    raw = int(obs.blstats[BLSTATS_IDX["strength"]])  # 3..125 encoding
    if raw <= 18:
        return str(raw)
    if raw <= 118:
        pct = raw - 18
        return "18/**" if pct >= 100 else f"18/{pct:02d}"
    return str(raw - 100)  # 119..125 -> 19..25


def _dungeon_name(env, dnum: int) -> str:
    for d in env._engine.dungeon_table():
        if d["dnum"] == dnum:
            return d["name"]
    return f"dnum {dnum}"


_PLANES = {5: "Plane of Earth", 4: "Plane of Air", 3: "Plane of Fire",
           2: "Plane of Water", 1: "Plane of Astral"}


def _label(env, obs) -> str:
    dnum = int(obs.blstats[BLSTATS_IDX["dungeon_number"]])
    depth = int(obs.blstats[BLSTATS_IDX["depth"]])
    pos = env.curriculum_position
    name = _dungeon_name(env, dnum)
    if "Elemental" in name and pos is not None:
        return _PLANES.get(pos[1], name)
    return f"{name}  Dlvl {depth}"


def _status(obs) -> str:
    b = obs.blstats
    xp = int(b[BLSTATS_IDX["experience_level"]])
    hp = int(b[BLSTATS_IDX["hitpoints"]])
    mhp = int(b[BLSTATS_IDX["max_hitpoints"]])
    return f"XP-level {xp}   HP {hp}/{mhp}   Str {_strength_str(obs)}"


def _capture(env, obs, phase, note=""):
    rows, colors = _obs_rows(obs)
    cap = f"{phase}:  {_label(env, obs)}"
    if note:
        cap += f"   <<< {note}"
    return frame(rows, colors, cap, status_text=_status(obs))


def build(seed: int):
    # ---- Descent ----
    env = CurriculumEnv()
    obs, _ = env.reset(seeds=(seed, seed))
    frames = [_capture(env, obs, "DESCENT")]
    prev_xp = int(obs.blstats[BLSTATS_IDX["experience_level"]])
    for _ in range(5):
        obs, _, _, _, info = env.step(DOWN)
        note = "JUMP + STAT UPGRADE" if "upgrade" in info else ""
        # Repeat the jump frame so the upgrade is readable in the animation.
        f = _capture(env, obs, "DESCENT", note)
        frames.append(f)
        if note:
            frames.append(f)
            frames.append(f)
    descent = save_gif("curriculum_descent", frames, duration=900)

    # ---- Ascent ----
    env = CurriculumEnv()
    obs, _ = env.reset(seeds=(seed, seed))
    for _ in range(5):  # get to the bottom (Gehennom 50)
        obs, *_ = env.step(DOWN)
    frames = [_capture(env, obs, "ASCENT")]
    for _ in range(10):
        obs, _, _, _, info = env.step(UP)
        to = info.get("to")
        note = ""
        if info.get("curriculum") == "ascend" and to is not None:
            frm = info.get("from")
            # Mark the two cross-branch jumps (Gehennom->DoD, DoD->Planes).
            if frm and frm[0] != to[0]:
                note = "JUMP"
        f = _capture(env, obs, "ASCENT", note)
        frames.append(f)
        if note:
            frames.append(f)
    ascent = save_gif("curriculum_ascent", frames, duration=900)
    return descent, ascent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=19)
    args = ap.parse_args()
    d, a = build(args.seed)
    print(f"descent: {d}\nascent:  {a}")


if __name__ == "__main__":
    main()
