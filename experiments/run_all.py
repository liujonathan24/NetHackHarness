"""Run every implemented experiment and emit a summary table."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EXPERIMENTS = [
    ("exp01_seeding", "01-seeding-and-nethackscore"),
    ("exp02_scout_reward", "02-scout-reward-delta"),
    ("exp03_menu_masking", "03-menu-region-masking"),
    ("exp04_bootstrap", "04-bootstrap-character"),
    ("exp05_terminal_detection", "05-terminal-outcome-detection"),
    ("exp08_autoexplore", "08-pathfinding-and-autoexplore"),
    ("exp13_code_mode", "13-code-mode"),
    ("exp14_subgoal_achievement", "14-dynamic-subgoals"),
    ("exp15_token_savings", "15-token-savings (post-survey compaction)"),
]


_OK_VERDICTS = {"FIX CONFIRMED", "SHIPS", "BASELINE"}


def main() -> int:
    rows = []
    failures = 0
    for mod_name, doc in EXPERIMENTS:
        try:
            mod = importlib.import_module(f"experiments.{mod_name}")
            r = mod.run()
            verdict = r["verdict"]
            rows.append((mod_name, doc, verdict))
            if verdict not in _OK_VERDICTS:
                failures += 1
        except Exception as e:
            rows.append((mod_name, doc, f"ERROR: {type(e).__name__}: {e}"))
            failures += 1

    print(f"{'experiment':<25} {'onboarding doc':<43} verdict")
    print("-" * 90)
    for name, doc, verdict in rows:
        print(f"{name:<25} {doc:<43} {verdict}")

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
