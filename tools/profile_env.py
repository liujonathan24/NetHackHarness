"""
Microbenchmarks for the layer-1 hot path.

Measures:
  * raw NLE step throughput (steps/sec)
  * observations.shape() throughput
  * pathfinding.a_star() throughput

Output is a single table. No file writes. Run:
    source .venv/bin/activate
    python tools/profile_env.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from nethack_core.env import NetHackCoreEnv
from nethack_core.observations import shape
from nethack_harness.navigation.pathfinding import a_star, nearest_frontier


def _bench(label: str, fn, n: int) -> None:
    # Warm-up.
    fn()
    start = time.perf_counter()
    for _ in range(n):
        fn()
    dt = time.perf_counter() - start
    per_call_ms = dt / n * 1000
    per_sec = n / dt
    print(f"  {label:40s}  {per_call_ms:8.3f} ms/call   {per_sec:10.0f} calls/sec")


def main() -> None:
    print("\nnethack-rl layer-1 microbench")
    print("-" * 70)

    env = NetHackCoreEnv(task_name="NetHackScore-v0")
    env.seed(core=42, disp=42)
    obs, _ = env.reset()

    # NetHackScore actions: 1 == N, 2 == E, etc.
    # We use action 0 (MORE/escape) which is a no-op after reset most turns
    # so we don't quickly die or change the map.
    def step_call():
        env.step(1)  # N step; will walk into walls but doesn't error

    _bench("NLE step (1 action)", step_call, n=2000)

    # Reset for the obs.shape() bench so map is in a known state.
    env.seed(core=42, disp=42)
    obs, _ = env.reset()
    character = {"role": "monk", "race": "human", "alignment": "neutral", "gender": "male"}

    def shape_call():
        shape(obs, character)

    _bench("observations.shape()", shape_call, n=2000)

    chars = obs.chars
    start_xy = (int(obs.blstats[0]), int(obs.blstats[1]))
    # Pick a reachable goal a few tiles away.
    goal = (start_xy[0] + 5, start_xy[1])

    def a_star_call():
        a_star(chars, start_xy, goal)

    _bench("a_star (~5-step path)", a_star_call, n=2000)

    def frontier_call():
        nearest_frontier(chars, start_xy)

    _bench("nearest_frontier (whole map)", frontier_call, n=500)

    env.close()
    print()
    print("Interpretation:")
    print("  - NLE step is the floor (~70-100 us). Everything above ~1 ms/call")
    print("    is layer-2 Python overhead. The verifiers `env_response` does")
    print("    obs.shape + format_observation_as_chat + tokenize per step;")
    print("    expect 2-5 ms/call there (untested in this script).")
    print()


if __name__ == "__main__":
    main()
