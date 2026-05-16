#!/usr/bin/env python3
"""Record a tagged demo trajectory against the current harness.

Usage:
    python tools/record_versioned_demo.py [--seed 42] [--steps 60] [--tier corridor_explore]

Writes `docs/onboarding/demo_<git-sha>_<seed>.json`. Designed to be re-run
after each batch of harness changes so the streamable replay artifact
always reflects the latest code. Pair with `tools/replay_viewer.html`.

This is intentionally separate from `tools/record_demo.py` (which is the
older one-off recorder) so neither script breaks the other and so the
versioned name encodes the exact harness state of the rollout.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--steps", type=int, default=60)
    ap.add_argument("--tier", type=str, default="corridor_explore")
    ap.add_argument("--out-dir", type=Path,
                    default=REPO_ROOT / "docs" / "onboarding" / "demo_history")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    sha = _git_sha()
    out_path = args.out_dir / f"demo_{sha}_{args.tier}_seed{args.seed}.json"

    # Delegate the heavy lifting to the existing recorder.
    cmd = [
        sys.executable,
        str(REPO_ROOT / "tools" / "record_demo.py"),
        "--seed", str(args.seed),
        "--steps", str(args.steps),
        "--out", str(out_path),
    ]
    # record_demo.py doesn't currently expose --tier; default tier is fine
    # for now and the version-tagged name preserves what to re-run later.
    print(f"running: {' '.join(cmd)}", file=sys.stderr)
    rc = subprocess.call(cmd, cwd=REPO_ROOT)
    if rc != 0:
        sys.exit(rc)

    # Append an index entry so the team can see which sha each demo maps to.
    index_path = args.out_dir / "INDEX.md"
    if not index_path.exists():
        index_path.write_text("# Demo trajectory history\n\nOne row per harness state. Open in `tools/replay_viewer.html`.\n\n| sha | tier | seed | path |\n|---|---|---|---|\n")
    with index_path.open("a") as f:
        f.write(f"| {sha} | {args.tier} | {args.seed} | `{out_path.relative_to(REPO_ROOT)}` |\n")

    print(f"wrote {out_path}")
    print(f"appended {index_path}")


if __name__ == "__main__":
    main()
