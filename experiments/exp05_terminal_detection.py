"""exp05 — terminal outcome detection: ascension/death now actually fires.

Bug: v0 of `_detect_terminal_outcome` was a stub. `state["ascended"]` and
`state["died"]` were never set, so `ascension_reward` (weight=1000) silently
always returned 0 even on a winning ascension. The 1000 weight was a no-op.

Fix: scan the final tty for known marker substrings ("ascended to demigod",
"killed by", etc.) and set the flags. Reward functions read the precomputed
booleans.

This experiment fabricates two terminal observations (one ascension, one
death) and runs both legacy and fixed detectors, then runs ascension_reward
on the resulting states. Verdict = FIX CONFIRMED if fixed detects both
outcomes correctly and reward fires only on ascension.
"""
from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nethack import _detect_terminal_outcome, ascension_reward

OUT_DIR = Path(__file__).parent / "results"
OUT_DIR.mkdir(exist_ok=True)


@dataclass
class FakeObs:
    tty_chars: np.ndarray


def _tty_with(text: str) -> np.ndarray:
    """24x80 tty containing `text` on a few middle rows."""
    arr = np.full((24, 80), 32, dtype=np.uint8)  # spaces
    lines = text.splitlines()
    for y, line in enumerate(lines, start=10):
        for x, ch in enumerate(line[:80]):
            arr[y, x] = ord(ch)
    return arr


def legacy_detect(obs, state: dict) -> None:
    """v0 stub: do nothing. ascended/died never get set."""
    return


def run() -> dict:
    cases = {
        "ascension": _tty_with(
            "  Goodbye Conan the Demigod...\n"
            "  You ascended to demigod-hood with the Amulet of Yendor.\n"
            "  You are awarded 1000000 points."
        ),
        "death_killed": _tty_with(
            "  Goodbye Foo the Cleric...\n"
            "  You were killed by a kobold.\n"
            "  Do you want your possessions identified? "
        ),
        "death_starved": _tty_with(
            "  You starved to death."
        ),
        "alive": _tty_with(
            "  You hit the jackal. The jackal bites!"
        ),
    }

    results: dict = {"cases": {}}
    for name, tty in cases.items():
        obs = FakeObs(tty_chars=tty)

        # legacy: nothing happens
        legacy_state: dict = {}
        legacy_detect(obs, legacy_state)
        legacy_ascended = legacy_state.get("ascended", False)

        # fixed: real scan
        fixed_state: dict = {}
        _detect_terminal_outcome(obs, fixed_state)
        fixed_ascended = fixed_state.get("ascended", False)
        fixed_died = fixed_state.get("died", False)

        # ascension_reward fired?
        legacy_reward = asyncio.new_event_loop().run_until_complete(ascension_reward(state=legacy_state))
        fixed_reward = asyncio.new_event_loop().run_until_complete(ascension_reward(state=fixed_state))

        results["cases"][name] = {
            "legacy_ascended": bool(legacy_ascended),
            "legacy_reward": float(legacy_reward),
            "fixed_ascended": bool(fixed_ascended),
            "fixed_died": bool(fixed_died),
            "fixed_reward": float(fixed_reward),
        }

    # Verdict checks:
    asc = results["cases"]["ascension"]
    killed = results["cases"]["death_killed"]
    starved = results["cases"]["death_starved"]
    alive = results["cases"]["alive"]

    verdict_ok = (
        asc["fixed_ascended"] and asc["fixed_reward"] == 1.0 and asc["legacy_reward"] == 0.0
        and killed["fixed_died"] and not killed["fixed_ascended"] and killed["fixed_reward"] == 0.0
        and starved["fixed_died"] and starved["fixed_reward"] == 0.0
        and not alive["fixed_ascended"] and not alive["fixed_died"]
    )
    results["verdict"] = "FIX CONFIRMED" if verdict_ok else "INCONCLUSIVE"

    (OUT_DIR / "exp05_terminal_detection.json").write_text(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    r = run()
    print(json.dumps(r, indent=2))
    print(f"\n{r['verdict']}")
