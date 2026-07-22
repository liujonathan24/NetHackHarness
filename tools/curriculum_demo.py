"""Local smoke runner: drive the curriculum env end-to-end with the skill
registry (the same descend/ascend skills the LLM approaches call) and print the
traversal. No model / API needed — proves the curriculum is agent-drivable.

    python tools/curriculum_demo.py --seed 19
"""
from __future__ import annotations

import argparse
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "environments" / "nethack"))

from nethack_core import CurriculumEnv  # noqa: E402
from nethack_core import BLSTATS_IDX  # noqa: E402
from nethack_core import shape as shape_observation  # noqa: E402
from nethack_harness.tools.skills import registry  # noqa: E402


def _line(env, skill):
    b = env._last_observation.blstats
    return (f"  {skill:8s} dnum={int(b[BLSTATS_IDX['dungeon_number']]):>1} "
            f"depth={int(b[BLSTATS_IDX['depth']]):>3} "
            f"XP={int(b[BLSTATS_IDX['experience_level']]):>2} "
            f"HP={int(b[BLSTATS_IDX['hitpoints']])}/{int(b[BLSTATS_IDX['max_hitpoints']])} "
            f"pos={env.curriculum_position}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=19)
    args = ap.parse_args()

    env = CurriculumEnv()
    env.reset(seeds=(args.seed, args.seed))
    char = {"role": "Valkyrie"}

    def drive(skill, n):
        for _ in range(n):
            so = shape_observation(env._last_observation, char)
            res = registry.call(skill, env, so)
            for a in res.actions:
                env.step(a)
            print(_line(env, skill))

    print(f"curriculum demo (seed {args.seed})")
    print("DESCEND: DoD 1->2->3 -> JUMP to Gehennom 48 (+upgrade) -> 49 -> 50")
    drive("descend", 5)
    print("ASCEND: 50->49->48 -> JUMP to DoD 3 -> 2 -> 1 -> JUMP to planes Earth->Astral")
    drive("ascend", 10)


if __name__ == "__main__":
    main()
