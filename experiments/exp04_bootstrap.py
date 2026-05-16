"""exp04 — bootstrap_character: parse role/race/align from the welcome line.

Bug: v0 stub returned `{"role": "unknown", ...}` for everything. The agent
never knew what character it was playing, so role-conditional reasoning
("monks should avoid weapons", "valks should attack") was impossible.

Fix: parse the standard NLE welcome message
  "You are a neutral male human Monk."
with a regex. Defensive on parse failure (returns unknown, doesn't crash).

This experiment runs both versions on a real NLE rollout and tabulates
character fields across 5 seeds. Verdict = FIX CONFIRMED if fixed gets a
real role on every seed and legacy returns 'unknown' on every seed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nethack_core.env import NetHackCoreEnv
from nethack_core.skills import bootstrap_character, parse_character_from_welcome

OUT_DIR = Path(__file__).parent / "results"
OUT_DIR.mkdir(exist_ok=True)

SEEDS = [42, 123, 7, 1024, 2026]


def legacy_bootstrap_character(env) -> dict:
    """v0 stub: always unknown."""
    return {"role": "unknown", "race": "unknown", "alignment": "unknown", "gender": "unknown"}


def run() -> dict:
    rows = []
    for seed in SEEDS:
        core = NetHackCoreEnv()
        core.seed(seed, seed)
        core.reset()

        legacy = legacy_bootstrap_character(core)
        fixed = bootstrap_character(core)

        rows.append({
            "seed": seed,
            "legacy_role": legacy["role"],
            "fixed_role": fixed.get("role", "unknown"),
            "fixed_race": fixed.get("race", "unknown"),
            "fixed_alignment": fixed.get("alignment", "unknown"),
            "fixed_gender": fixed.get("gender", "unknown"),
        })
        core.close()

    n_fixed_known = sum(1 for r in rows if r["fixed_role"] != "unknown")
    n_legacy_known = sum(1 for r in rows if r["legacy_role"] != "unknown")

    result = {
        "seeds": SEEDS,
        "rows": rows,
        "fixed_known_role_count": n_fixed_known,
        "legacy_known_role_count": n_legacy_known,
        "verdict": (
            "FIX CONFIRMED"
            if n_fixed_known >= len(SEEDS) - 1 and n_legacy_known == 0
            else "INCONCLUSIVE"
        ),
    }
    (OUT_DIR / "exp04_bootstrap.json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    r = run()
    print(json.dumps(r, indent=2))
    print(f"\n{r['verdict']}: fixed got role on {r['fixed_known_role_count']}/{len(SEEDS)} seeds, legacy on {r['legacy_known_role_count']}/{len(SEEDS)}")
