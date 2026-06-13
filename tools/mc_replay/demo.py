"""Demo: Monte-Carlo "checking" of candidate next actions on a live engine.

Run with::

    uv run python -m tools.mc_replay.demo

Constructs an EngineEnv, resets with a fixed seed, walks a handful of fixed
moves to get into the dungeon, then runs mc_lookahead over a small candidate
set (the 4 cardinal moves + search + descend) and prints the ranked results.
This shows MC evaluating which next action is most promising by branching the
live engine state.
"""

from __future__ import annotations

from nethack_core.engine_env import EngineEnv

from .core import mc_lookahead

# Raw ASCII action ints (the fork engine's convention; see test_snapshot.py).
MOVE_W = ord("h")
MOVE_E = ord("l")
MOVE_S = ord("j")
MOVE_N = ord("k")
SEARCH = ord("s")
DESCEND = ord(">")


def main() -> None:
    env = EngineEnv()
    env.seed(42, 42)
    obs, _meta = env.reset()

    # Step a handful of fixed moves to get into the dungeon.
    warmup = [MOVE_E, MOVE_E, MOVE_E, MOVE_S, MOVE_S]
    for a in warmup:
        obs, done, _info = env.step(a)
        if done:
            break

    print("=== mc_replay demo ===")
    print(
        f"start state: x={int(obs.blstats[0])} "
        f"y={int(obs.blstats[1])} depth={int(obs.blstats[12])}"
    )

    candidates = [MOVE_W, MOVE_E, MOVE_S, MOVE_N, SEARCH, DESCEND]
    results = mc_lookahead(
        env,
        candidates,
        horizon=20,
        n_branches=3,
        reseed=True,
    )

    print("\nranked MC results (best first):")
    print(f"{'action':>8}  {'mean_score':>11}  {'mean_depth_gain':>16}  {'death_rate':>11}")
    for r in results:
        a = r["action"]
        label = repr(chr(a)) if 32 <= a < 127 else str(a)
        print(
            f"{label:>8}  {r['mean_score']:>11.3f}  "
            f"{r['mean_depth_gain']:>16.3f}  {r['death_rate']:>11.3f}"
        )

    best = results[0]
    best_a = best["action"]
    best_label = repr(chr(best_a)) if 32 <= best_a < 127 else str(best_a)
    print(f"\nbest candidate: {best_label} (mean_score={best['mean_score']:.3f})")

    env.close()


if __name__ == "__main__":
    main()
