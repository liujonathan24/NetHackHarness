"""Side-by-side comparison of two vf-eval / prime-eval runs.

Reads metadata.json files from `outputs/evals/<model>/<hash>/metadata.json`
and emits a difference table covering reward, token use, per-skill calls,
and (estimated) cost. Useful for confirming a version bump actually moved
the needle vs introduced regressions.

Usage:
    python tools/compare_evals.py path/to/eval_A/metadata.json \\
                                  path/to/eval_B/metadata.json

    # or with the labels you'd see in the writeup:
    python tools/compare_evals.py --label-a v0.0.14 --label-b v0.0.16 \\
        outputs/evals/nethack--Qwen--Qwen3.5-9B/abc/metadata.json \\
        outputs/evals/nethack--Qwen--Qwen3.5-9B/def/metadata.json

If you don't pass paths, it picks the two most recent metadata.json files
under environments/nethack/outputs/evals/.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path


# Rough $/Mtok pricing for cost estimation. Update as needed.
_PRICING = {
    "Qwen/Qwen3.5-0.8B": (0.04, 0.08),
    "Qwen/Qwen3.5-2B":   (0.06, 0.18),
    "Qwen/Qwen3.5-4B":   (0.10, 0.30),
    "Qwen/Qwen3.5-9B":   (0.18, 0.54),
    "Qwen/Qwen3.5-122B-A10B": (0.30, 0.90),
    "qwen/qwen3.5-35b-a3b": (0.3125, 1.80),
}


def _cost(model: str, input_tok: float, output_tok: float) -> float:
    pricing = _PRICING.get(model)
    if pricing is None:
        return -1.0
    return (input_tok / 1e6) * pricing[0] + (output_tok / 1e6) * pricing[1]


def _delta_pct(a: float, b: float) -> str:
    if a == 0:
        return "—" if b == 0 else "+∞%"
    pct = (b - a) / abs(a) * 100
    return f"{pct:+.1f}%"


def _load(p: str) -> dict:
    return json.loads(Path(p).read_text())


def _find_recent_evals(n: int = 2) -> list[Path]:
    base = Path("environments/nethack/outputs/evals")
    if not base.exists():
        return []
    files = sorted(base.glob("*/*/metadata.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:n]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("paths", nargs="*", help="Two metadata.json paths (or omit for most-recent)")
    p.add_argument("--label-a", default=None)
    p.add_argument("--label-b", default=None)
    args = p.parse_args()

    if len(args.paths) == 2:
        path_a, path_b = args.paths
    elif len(args.paths) == 0:
        recent = _find_recent_evals(2)
        if len(recent) < 2:
            print("Need at least 2 metadata.json files to compare. Pass paths.", file=sys.stderr)
            return 1
        path_b, path_a = recent  # most recent = B; second = A
    else:
        print("Pass exactly two paths or zero (auto-pick).", file=sys.stderr)
        return 1

    a = _load(path_a)
    b = _load(path_b)

    label_a = args.label_a or f"A ({Path(path_a).parent.name})"
    label_b = args.label_b or f"B ({Path(path_b).parent.name})"

    print(f"\nComparing:\n  A: {path_a}\n  B: {path_b}\n")
    print(f"Model: A={a.get('model')} | B={b.get('model')}")
    print(f"Env version: A={a.get('version_info', {}).get('env_version')} | B={b.get('version_info', {}).get('env_version')}")
    print(f"Examples × rollouts: A={a.get('num_examples')}×{a.get('rollouts_per_example')} | B={b.get('num_examples')}×{b.get('rollouts_per_example')}")
    print()

    print(f"{'metric':<24} {label_a:>14} {label_b:>14} {'Δ':>10}")
    print("-" * 64)
    rows = [
        ("avg_reward", a.get("avg_reward", 0), b.get("avg_reward", 0)),
        ("scout_reward", a.get("avg_metrics", {}).get("scout_reward", 0), b.get("avg_metrics", {}).get("scout_reward", 0)),
        ("descent_reward", a.get("avg_metrics", {}).get("descent_reward", 0), b.get("avg_metrics", {}).get("descent_reward", 0)),
        ("success_reward", a.get("avg_metrics", {}).get("success_reward", 0), b.get("avg_metrics", {}).get("success_reward", 0)),
        ("num_turns", a.get("avg_metrics", {}).get("num_turns", 0), b.get("avg_metrics", {}).get("num_turns", 0)),
        ("total_tool_calls", a.get("avg_metrics", {}).get("total_tool_calls", 0), b.get("avg_metrics", {}).get("total_tool_calls", 0)),
        ("input_tokens", a.get("usage", {}).get("input_tokens", 0), b.get("usage", {}).get("input_tokens", 0)),
        ("output_tokens", a.get("usage", {}).get("output_tokens", 0), b.get("usage", {}).get("output_tokens", 0)),
    ]
    for name, va, vb in rows:
        try:
            print(f"{name:<24} {va:>14.4f} {vb:>14.4f} {_delta_pct(float(va), float(vb)):>10}")
        except (TypeError, ValueError):
            print(f"{name:<24} {str(va)[:14]:>14} {str(vb)[:14]:>14} {'?':>10}")

    print()
    cost_a = _cost(a.get("model", ""), a.get("usage", {}).get("input_tokens", 0), a.get("usage", {}).get("output_tokens", 0))
    cost_b = _cost(b.get("model", ""), b.get("usage", {}).get("input_tokens", 0), b.get("usage", {}).get("output_tokens", 0))
    if cost_a >= 0 and cost_b >= 0:
        print(f"Estimated cost: A=${cost_a:.3f} | B=${cost_b:.3f} | Δ {_delta_pct(cost_a, cost_b)}")
    else:
        print("Cost not estimated (unknown model pricing).")

    # Top differing skill calls.
    am = a.get("avg_metrics", {})
    bm = b.get("avg_metrics", {})
    print(f"\nTop diverging skill calls (|Δ| ≥ 5):")
    skill_keys = sorted({k for k in (am.keys() | bm.keys()) if k.endswith("_calls")})
    for k in skill_keys:
        va = float(am.get(k, 0))
        vb = float(bm.get(k, 0))
        if abs(va - vb) >= 5:
            print(f"  {k:<28} A={va:>6.1f}  B={vb:>6.1f}  Δ={vb-va:+.1f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
