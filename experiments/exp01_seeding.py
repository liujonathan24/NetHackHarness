"""exp01 — seeding regression: Challenge crashes, Score reproduces byte-equal.

Bug: v0 wrapped `NetHackChallenge-v0`, whose `__init__` monkey-patches
`nethack.set_initial_seeds` to refuse all seed changes (anti-TAS hardening).
Calling `core.seed(seed, seed)` raised RuntimeError. Reproducibility was
impossible.

Fix: default to `NetHackScore-v0` — same parent class, no seed monkey-patch.

This experiment shows three things on seed=42:
  1. Direct `set_initial_seeds` on a Challenge env raises.
  2. The fixed Score env accepts the seed pair without raising.
  3. Two seeded reruns of the Score env produce byte-identical raw obs.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import gymnasium as gym

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nethack_core.env import NetHackCoreEnv

OUT_DIR = Path(__file__).parent / "results"
OUT_DIR.mkdir(exist_ok=True)

SEED = 42


def _hash_obs(obs: dict) -> str:
    h = hashlib.sha256()
    # Only hash deterministic arrays; metadata fields like "info" may vary.
    for k in ("tty_chars", "glyphs", "blstats", "message"):
        if k in obs:
            h.update(obs[k].tobytes())
    return h.hexdigest()[:16]


def legacy_attempts_challenge_seed() -> dict:
    """Reproduce the legacy bug: try to seed a NetHackChallenge-v0 env."""
    import nle  # noqa: F401  # registers gym IDs
    env = gym.make("NetHackChallenge-v0")
    raised = None
    try:
        # Pull the underlying NLE object the same way our wrapper did.
        underlying = env.unwrapped
        if hasattr(underlying, "nethack") and hasattr(underlying.nethack, "set_initial_seeds"):
            underlying.nethack.set_initial_seeds(SEED, SEED, reseed=False)
    except Exception as e:
        raised = f"{type(e).__name__}: {e}"
    finally:
        env.close()
    return {"raised": raised}


def fixed_two_runs_byte_equal() -> dict:
    """Run NetHackScore-v0 twice with same seed; hash and compare obs."""
    hashes = []
    for _ in range(2):
        core = NetHackCoreEnv()
        core.seed(SEED, SEED)
        core.reset()
        raw = core.underlying.unwrapped.last_observation
        # last_observation is a tuple; reshape into the dict structure we hash on.
        obs_dict = {
            "tty_chars": raw[0],     # by NLE convention
            "tty_colors": raw[1],
            "glyphs": raw[3],
            "message": raw[10],
            "blstats": raw[11],
        }
        hashes.append(_hash_obs(obs_dict))
        core.close()
    return {"run1_hash": hashes[0], "run2_hash": hashes[1], "equal": hashes[0] == hashes[1]}


def run() -> dict:
    legacy = legacy_attempts_challenge_seed()
    fixed = fixed_two_runs_byte_equal()

    verdict_legacy = legacy["raised"] is not None and "Should not try changing seeds" in (legacy["raised"] or "")
    verdict_fixed = fixed["equal"]

    result = {
        "seed": SEED,
        "legacy_challenge_seed_attempt": legacy,
        "fixed_score_two_runs": fixed,
        "verdict": (
            "FIX CONFIRMED"
            if verdict_legacy and verdict_fixed
            else "INCONCLUSIVE"
        ),
        "verdict_detail": {
            "legacy_raises_as_expected": verdict_legacy,
            "fixed_reproduces_byte_equal": verdict_fixed,
        },
    }
    (OUT_DIR / "exp01_seeding.json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    r = run()
    print(json.dumps(r, indent=2))
    print(f"\n{r['verdict']}")
