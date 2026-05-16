#!/usr/bin/env python3
"""Quick failure-mode summary for a verifiers eval results.jsonl.

Usage:
    python tools/trace_analyze.py PATH/TO/results.jsonl

Reports per-rollout:
- Tool call distribution + consecutive-same-tool runs >= 5
- Reasoning length percentiles (where available)
- Action feedback patterns (compacted vs fresh)
- Number of "stuck"-keyword markers in reasoning
- Whether the rollout descended, took damage, and hit any milestones

Optimized for the patterns that surfaced in trace 9071d001:
overlong autoexplore runs, glyph misidentification ("fireplace"/etc.),
pet-blocking loops, and stair-down hallucination.

This is a static-analysis tool — doesn't need an LM, doesn't need NLE.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path


STUCK_KEYWORDS = (
    "stuck", "looping", "loop", "cannot find", "no path", "in circles",
    "same map", "same position", "tried this already",
)
GLYPH_HALLUCINATIONS = (
    "fireplace", "fountain (f)", "fountain f", "floor (f)",
)


def _parse_tool_calls(msg: dict) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for t in (msg.get("tool_calls") or []):
        if isinstance(t, str):
            try:
                t = json.loads(t)
            except (TypeError, ValueError):
                continue
        name = t.get("name") or (t.get("function") or {}).get("name")
        args = t.get("arguments") or (t.get("function") or {}).get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (TypeError, ValueError):
                args = {}
        out.append((name, args or {}))
    return out


def analyze_rollout(r: dict) -> dict:
    c = r.get("completion") or []
    assistant_msgs = [m for m in c if m.get("role") == "assistant"]
    user_msgs = [m for m in c if m.get("role") == "user"]

    tool_seq: list[str] = []
    reasoning_lens: list[int] = []
    stuck_hits = 0
    glyph_hallucinations: list[str] = []
    for m in assistant_msgs:
        rc = m.get("reasoning_content") or ""
        if rc:
            reasoning_lens.append(len(rc))
        rcl = rc.lower()
        if any(kw in rcl for kw in STUCK_KEYWORDS):
            stuck_hits += 1
        for h in GLYPH_HALLUCINATIONS:
            if h in rcl:
                glyph_hallucinations.append(h)
        for name, _args in _parse_tool_calls(m):
            tool_seq.append(name)

    # Consecutive-same runs
    runs: list[tuple[str, int]] = []
    i = 0
    while i < len(tool_seq):
        j = i
        while j < len(tool_seq) and tool_seq[j] == tool_seq[i]:
            j += 1
        runs.append((tool_seq[i], j - i))
        i = j
    long_runs = [r for r in runs if r[1] >= 5]

    # User-feedback patterns: bracketed markers vs compacted-only lines
    bracket_count = 0
    compacted_only_count = 0
    compacted_unchanged_count = 0
    move_blocked_count = 0
    autoexplore_loop_count = 0
    pet_blocking_count = 0
    visible_features_lines = 0
    for u in user_msgs:
        content = u.get("content") or ""
        if isinstance(content, list):
            content = " ".join(str(x) for x in content)
        first = content[:80]
        if first.startswith("[Moved") or first.startswith("[Picked") or first.startswith("[Attack") or first.startswith("[Hit") or first.startswith("[Killed"):
            bracket_count += 1
        if re.match(r"^\[turn -\d+\]\s*HP: ", first) and "=== MAP" not in content[:200]:
            compacted_only_count += 1
        if "(unchanged)" in content[:60]:
            compacted_unchanged_count += 1
        if "Move blocked" in content[:300]:
            move_blocked_count += 1
        if "autoexplore-loop" in content[:300]:
            autoexplore_loop_count += 1
        if "is in the way" in content[:400] or "blocking your move" in content[:400]:
            pet_blocking_count += 1
        if "=== VISIBLE FEATURES ===" in content:
            visible_features_lines += 1

    return {
        "tool_total": len(tool_seq),
        "tool_distribution": dict(Counter(tool_seq)),
        "consecutive_long_runs": long_runs,
        "reasoning_chars_p50": int(statistics.median(reasoning_lens)) if reasoning_lens else 0,
        "reasoning_chars_p95": int(statistics.quantiles(reasoning_lens, n=20)[-1]) if len(reasoning_lens) >= 20 else (max(reasoning_lens) if reasoning_lens else 0),
        "reasoning_chars_max": max(reasoning_lens) if reasoning_lens else 0,
        "stuck_keyword_hits": stuck_hits,
        "glyph_hallucinations": Counter(glyph_hallucinations),
        "user_msgs_with_action_bracket": bracket_count,
        "user_msgs_compacted_only": compacted_only_count,
        "user_msgs_compacted_unchanged_collapse": compacted_unchanged_count,
        "move_blocked_hits": move_blocked_count,
        "autoexplore_loop_hint_hits": autoexplore_loop_count,
        "pet_blocking_hint_hits": pet_blocking_count,
        "visible_features_block_appearances": visible_features_lines,
        "scout_reward": r.get("scout_reward"),
        "descend_calls": r.get("descend_calls"),
        "num_turns": r.get("num_turns"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    args = ap.parse_args()
    with args.path.open() as f:
        for line in f:
            r = json.loads(line)
            out = analyze_rollout(r)
            print(json.dumps(out, indent=2, default=str))
            print()


if __name__ == "__main__":
    main()
