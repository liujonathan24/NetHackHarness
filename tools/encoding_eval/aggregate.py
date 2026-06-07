"""Pure aggregation: rollout samples per encoding -> comparison table.

Reuses tools.eval_instrument.summarize_eval and nethack_harness.prompt.balrog
progression metrics. No model calls — fully unit-testable on synthetic samples.
"""
from __future__ import annotations

from typing import Any


def _max_dlvl(sample: dict) -> int:
    if sample.get("max_dlvl") is not None:
        return int(sample["max_dlvl"])
    best = 0
    for e in sample.get("trace") or []:
        d = (e.get("status") or {}).get("depth")
        if d is not None:
            best = max(best, int(d))
    return best


def _xp(sample: dict) -> int:
    if sample.get("xp_level") is not None:
        return int(sample["xp_level"])
    best = 0
    for e in sample.get("trace") or []:
        x = (e.get("status") or {}).get("experience_level")
        if x is not None:
            best = max(best, int(x))
    return best


def aggregate_cells(cells: dict[str, list[dict]]) -> dict[str, Any]:
    from tools.eval_instrument import summarize_eval
    from nethack_harness.prompt.balrog import progression_score, progression_tier

    rows: dict[str, Any] = {}
    for enc, samples in cells.items():
        summ = summarize_eval(samples)
        max_dlvl = max((_max_dlvl(s) for s in samples), default=0)
        xp = max((_xp(s) for s in samples), default=0)
        score = progression_score(max_dlvl, xp)
        tokens = [s["tokens_per_turn"] for s in samples if s.get("tokens_per_turn") is not None]
        tokens_per_turn = (sum(tokens) / len(tokens)) if tokens else None
        costs = [s["dollars"] for s in samples if s.get("dollars") is not None]
        rows[enc] = {
            "n": summ["n"],
            "descent_rate": summ["descent_rate"],
            "ci_lo": summ["ci_lo"],
            "ci_hi": summ["ci_hi"],
            "avg_score": summ["avg_score"],
            "failure_taxonomy": summ["failure_taxonomy"],
            "max_dlvl": max_dlvl,
            "progression_score": score,
            "progression_tier": progression_tier(score),
            "tokens_per_turn": tokens_per_turn,
            "dollars_per_run": (sum(costs) / len(costs)) if costs else None,
        }
    return {"rows": rows}


def table_to_markdown(table: dict) -> str:
    cols = ["n", "descent_rate", "progression_tier", "max_dlvl", "tokens_per_turn", "dollars_per_run"]
    lines = ["| encoding | " + " | ".join(cols) + " |",
             "|---|" + "|".join("---" for _ in cols) + "|"]
    for enc, r in table["rows"].items():
        cells = [("n/a" if r[c] is None else r[c]) for c in cols]
        lines.append(f"| {enc} | " + " | ".join(str(c) for c in cells) + " |")
    return "\n".join(lines)
