"""exp02 — scout reward delta vs cumulative.

Bug: the v0 scout reward returned `len(scout_tiles_seen) / 1000` — a
cumulative count of every tile ever scouted. A stationary agent kept being
paid for tiles it had already revealed turns ago.

Fix: return the *delta* between pre- and post-step tile-set sizes. The new
env_response captures `scout_delta` each step; the reward function returns
that.

This experiment runs a real NLE rollout under both reward functions on the
same seed and same action trace, then plots step → reward for each. Under
the fix, the curve flattens to 0 once exploration stalls; under the bug,
the curve stays high indefinitely.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nethack_core.env import NetHackCoreEnv

OUT_DIR = Path(__file__).parent / "results"
OUT_DIR.mkdir(exist_ok=True)

SEED = 42
N_EXPLORE_STEPS = 40   # the agent moves around
N_STATIONARY_STEPS = 60  # then waits in place


def legacy_scout_reward(scout_tiles_seen: set, scout_delta: int) -> float:
    """The v0 bug: cumulative count, ignores delta."""
    return len(scout_tiles_seen) / 1000.0


def fixed_scout_reward(scout_tiles_seen: set, scout_delta: int) -> float:
    """The current code: per-step delta."""
    return scout_delta / 1000.0


def _iterate_visible_tiles(obs):
    chars = obs["tty_chars"]
    for y in range(1, chars.shape[0] - 2):
        for x in range(chars.shape[1]):
            yield (x, y), chars[y : y + 1, x : x + 1].tobytes()


def run() -> dict:
    core = NetHackCoreEnv()
    core.seed(SEED, SEED)
    core.reset()
    env = core.underlying  # raw NLE gym env: step() returns dict with tty_chars

    # Action indices for NetHackScore: 0=more, 1=N, 2=E, 3=S, 4=W, 5=NE, ...
    # 18=search (effectively wait in place).
    rng = np.random.default_rng(SEED)
    move_actions = [int(rng.integers(1, 9)) for _ in range(N_EXPLORE_STEPS)]
    wait_actions = [18] * N_STATIONARY_STEPS
    actions = move_actions + wait_actions

    scout_tiles: set = set()
    legacy_rewards = []
    fixed_rewards = []

    dlvl = 1
    for action in actions:
        before = len(scout_tiles)
        obs, _r, term, trunc, _info = env.step(action)
        for (x, y), ch in _iterate_visible_tiles(obs):
            if ch not in (b" ", b"\x00"):
                scout_tiles.add((dlvl, x, y))
        delta = len(scout_tiles) - before

        legacy_rewards.append(legacy_scout_reward(scout_tiles, delta))
        fixed_rewards.append(fixed_scout_reward(scout_tiles, delta))

        if term or trunc:
            break

    n = len(legacy_rewards)
    explore_phase = slice(0, min(N_EXPLORE_STEPS, n))
    stationary_phase = slice(N_EXPLORE_STEPS, n)

    result = {
        "seed": SEED,
        "n_steps": n,
        "legacy": {
            "explore_mean": float(np.mean(legacy_rewards[explore_phase])),
            "stationary_mean": float(np.mean(legacy_rewards[stationary_phase]) if n > N_EXPLORE_STEPS else 0.0),
            "final": float(legacy_rewards[-1]),
        },
        "fixed": {
            "explore_mean": float(np.mean(fixed_rewards[explore_phase])),
            "stationary_mean": float(np.mean(fixed_rewards[stationary_phase]) if n > N_EXPLORE_STEPS else 0.0),
            "final": float(fixed_rewards[-1]),
        },
    }
    # Verdict: under the fix, stationary-phase mean should be ~0.
    # Under the bug, stationary-phase mean ≈ final cumulative count.
    result["verdict"] = (
        "FIX CONFIRMED"
        if result["fixed"]["stationary_mean"] < 0.01
        and result["legacy"]["stationary_mean"] > 10 * result["fixed"]["stationary_mean"]
        else "INCONCLUSIVE"
    )

    (OUT_DIR / "exp02_scout_reward.json").write_text(json.dumps(result, indent=2))

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 4))
        steps = np.arange(n)
        ax.plot(steps, legacy_rewards, label="legacy (cumulative)", color="C3", lw=2)
        ax.plot(steps, fixed_rewards, label="fixed (delta)", color="C0", lw=2)
        ax.axvline(N_EXPLORE_STEPS, color="gray", linestyle="--", alpha=0.5)
        ax.text(N_EXPLORE_STEPS + 0.5, ax.get_ylim()[1] * 0.9, "stationary →", color="gray")
        ax.set_xlabel("step")
        ax.set_ylabel("scout_reward (per step)")
        ax.set_title(f"exp02: scout reward — legacy pays standing still; fix does not (seed={SEED})")
        ax.legend()
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(OUT_DIR / "exp02_scout_reward.png", dpi=120)
        plt.close(fig)
    except ImportError:
        print("(matplotlib not installed — skipping plot; numbers in JSON)")

    return result


if __name__ == "__main__":
    r = run()
    print(json.dumps(r, indent=2))
    print(f"\n{r['verdict']}: legacy_stationary={r['legacy']['stationary_mean']:.4f}  fixed_stationary={r['fixed']['stationary_mean']:.4f}")
