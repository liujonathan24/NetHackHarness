"""
Record a sample trajectory for the replay viewer.

Usage:
    source .venv/bin/activate
    python tools/record_demo.py [--seed 42] [--steps 60] [--out PATH]

The script:
  * spins up a NetHackScore env at the given seed
  * bootstraps the character from the welcome message
  * pins an objective in the journal and writes one note
  * autoexplores the level for `--steps` steps, capturing every frame
  * saves a Trajectory JSON the viewer can open directly

The resulting JSON is the artifact you'd open in tools/replay_viewer.html
or share as the Monday demo input.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running this script directly from the repo root without `pip install -e`.
# The editable install puts nethack_core's contents at sys.path top-level, which
# is fine for tests under pytest (which adds the rootdir to sys.path) but bites
# scripts launched via `python tools/record_demo.py`. Standalone src-layout
# refactor is on the followup list; for now this one-line tweak keeps the demo
# usable from a fresh clone.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nethack_core.env import NetHackCoreEnv
from nethack_core.journal import Journal
from nethack_core.replay import TrajectoryRecorder
from nethack_core.skills import autoexplore, bootstrap_character


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--steps", type=int, default=60, help="Hard cap on env steps")
    p.add_argument("--max-trips", type=int, default=20, help="Hard cap on autoexplore calls")
    p.add_argument("--out", type=Path, default=Path("/tmp/nethack_demo.json"))
    args = p.parse_args()

    env = NetHackCoreEnv(task_name="NetHackScore-v0")
    rec = TrajectoryRecorder(env)
    rec.reset(seeds=(args.seed, args.seed))
    character = bootstrap_character(env)

    # Set up a journal so the recorded trajectory shows what the agent's
    # memory state looks like over time. This lets the viewer demo the
    # journal block end-to-end.
    journal = Journal()
    journal.pin_objective("Explore dungeon level 1 fully, then descend.")
    journal.add_note("character", f"{character['alignment']} {character['race']} {character['role']}")

    total_steps = 0
    for trip in range(args.max_trips):
        if total_steps >= args.steps:
            break
        r = autoexplore(env, None, max_steps=10)
        if not r.actions:
            # Frontier exhausted; level fully revealed.
            journal.add_note("status", "level fully explored")
            break
        skill_meta = {"name": "autoexplore", "args": {"max_steps": 10}}
        for a in r.actions:
            if total_steps >= args.steps:
                break
            _, _, term, trunc, _ = rec.step(
                a,
                skill=skill_meta,
                journal={"objective": journal.objective, "notes": dict(journal.notes)},
            )
            total_steps += 1
            if term or trunc:
                break
        if term or trunc:
            break

    traj = rec.export(final_status={"note": "demo trajectory"}, character=character)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    traj.save(args.out)
    print(f"Saved {args.out}")
    print(f"  seeds={traj.seeds}")
    print(f"  character={character}")
    print(f"  frames={len(traj.frames)}  actions={len(traj.actions)}  total_reward={sum(traj.rewards):.3f}")


if __name__ == "__main__":
    main()
