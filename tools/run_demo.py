"""One-command Monday demo runner.

Produces, in order:
  1. Test sweep (`pytest tests/`) — substrate sanity.
  2. Regression experiments (`experiments/run_all.py`) — verdict table.
  3. Baseline-agent reward distribution (`baseline_agents.py`) — what
     the env looks like before any LM training.
  4. Recorded trajectory (`tools/record_demo.py`) — opens in the replay
     viewer.
  5. Optional `vf-eval` smoke against an LM if --model is provided.

Usage:
    python tools/run_demo.py
    python tools/run_demo.py --model gpt-4.1-mini   # extra: live eval
    python tools/run_demo.py --skip-tests           # in case you've already run them
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "experiments" / "results"


def _section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def _run(cmd: list[str], cwd: Path = ROOT) -> int:
    print(f"$ {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=str(cwd))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", help="If set, run vf-eval against this model (1 example, 1 rollout)")
    p.add_argument("--endpoints", default="configs/endpoints.toml")
    p.add_argument("--skip-tests", action="store_true")
    args = p.parse_args()

    py = sys.executable
    started = time.time()

    if not args.skip_tests:
        _section("1/5: pytest sanity")
        if _run([py, "-m", "pytest", "tests/", "-q"]) != 0:
            print("\nTests failed; aborting demo.")
            return 1

    _section("2/5: regression experiments (run_all)")
    _run([py, "experiments/run_all.py"])

    _section("2b/5: build the experiment Markdown report")
    _run([py, "experiments/build_report.py"])
    print(f"Open: {ROOT / 'experiments' / 'REPORT.md'}")

    _section("3/5: baseline reward distribution (corridor_explore, 3 seeds × 50 steps)")
    _run([py, "experiments/baseline_agents.py", "--seeds", "3", "--max-steps", "50"])

    _section("4/5: record a sample trajectory for the replay viewer")
    out = ROOT / "docs" / "onboarding" / "demo_trajectory.json"
    _run([py, "tools/record_demo.py", "--out", str(out)])
    if out.exists():
        print(f"Replay this in your browser:")
        print(f"  open tools/replay_viewer.html  ← then load {out.relative_to(ROOT)}")

    if args.model:
        _section(f"5/5: live eval against {args.model}")
        if "OPENAI_API_KEY" not in os.environ and "ANTHROPIC_API_KEY" not in os.environ and "PI_API_KEY" not in os.environ:
            print("(no API key in env — skipping live eval; set OPENAI_API_KEY/ANTHROPIC_API_KEY/PI_API_KEY)")
        else:
            _run(["vf-eval", "nethack", "-m", args.model, "-n", "1", "-r", "1",
                  "--endpoints", args.endpoints])
    else:
        _section("5/5: live eval (skipped — pass --model to enable)")
        print("Try one of:")
        print("  --model gpt-4.1-mini      (needs OPENAI_API_KEY)")
        print("  --model claude-haiku-4-5  (needs ANTHROPIC_API_KEY)")
        print("  --model Qwen/Qwen3-32B    (needs PI_API_KEY, free)")

    _section(f"DONE in {time.time() - started:.1f}s")
    print(f"Outputs:")
    print(f"  - experiments/results/*.json + *.png")
    print(f"  - {out.relative_to(ROOT) if out.exists() else 'docs/onboarding/demo_trajectory.json'}")
    print(f"  - tools/replay_viewer.html (open in browser)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
