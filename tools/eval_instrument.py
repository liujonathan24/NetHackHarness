"""Wave-3 Track A: descent-rate confidence intervals + failure taxonomy.

This module turns the existing per-rollout eval output into the two
quantities the harness actually needs to compare variants at small n:

1. Binary descent outcome per rollout (descent_reward >= 1) aggregated
   into a success rate with a Wilson 95% CI.
2. Failure taxonomy per non-descending rollout, derived rule-based from
   either a local NDJSON trace (see `_write_trace_entry` in
   `environments/nethack/nethack.py`) or, when no trace is available,
   from the hosted-eval sample's `prompt`+`completion` messages.

Designed to be imported by `tools/compare_evals.py` and the dashboard.

Public surface:
    wilson_ci(k, n, z=1.96) -> (lo, hi)
    classify_failure(rollout) -> str  # one of FAILURE_MODES
    summarize_eval(samples) -> dict
    comparison_table(name_a, samples_a, name_b, samples_b) -> str  (markdown)

A rollout is a dict with (at minimum) the keys produced by hosted
`prime eval get --output json`:
    completion: list[{role, content, tool_calls?}]
    prompt:     list[...] (optional, currently unused)
    descent_reward, scout_reward, success_reward, ascension_reward
    info: {is_completed, is_truncated, metrics: {...}}
Optionally `trace`: list[dict] (one entry per turn) if a local NDJSON
trace is loaded alongside.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# Failure taxonomy
# ---------------------------------------------------------------------------

FAILURE_MODES = (
    "starved",
    "killed_by_monster",
    "turn_budget",
    "stuck_no_progress",
    "door_block",
    "other",
)

# Substrings that show up verbatim in the last few user messages or in
# the NLE topscore banner once the run ends. Order matters for the
# classify_failure cascade.
_STARVED_PAT = re.compile(r"\b(starv|starved to death|died of starvation|food poisoning)\b", re.I)
_KILLED_PAT = re.compile(r"\b(killed by|slain by|was killed)\b", re.I)
_DOOR_SAW_PAT = re.compile(r"\b(door|closed door|\+ \(door\))\b", re.I)
_DOOR_OPENED_PAT = re.compile(r"\b(opened|kicked|broke|smashed)[^\n]{0,30}door\b", re.I)


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    p_hat = k/n. The Wilson lower/upper bounds are:
        (p_hat + z^2/2n  ±  z * sqrt( p_hat*(1-p_hat)/n + z^2/(4n^2) ))
        / (1 + z^2/n)

    Returns (0.0, 0.0) when n == 0 (caller decides how to display).
    """
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = (p + z2 / (2.0 * n)) / denom
    half = (z * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n))) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _iter_text(rollout: dict, sources: Iterable[str] = ("trace", "completion", "prompt")) -> list[str]:
    """Return a list of user-visible text blobs (in turn order) for scanning.

    Preference order: a per-turn NDJSON trace (richest, includes raw_grid),
    then the hosted-eval `completion` messages, then `prompt` as a fallback.
    """
    out: list[str] = []
    trace = rollout.get("trace")
    if trace:
        for entry in trace:
            # rendered_user_message is exactly what the model saw
            msg = entry.get("rendered_user_message") or ""
            if msg:
                out.append(msg)
            # raw_grid often carries the death banner verbatim
            grid = entry.get("raw_grid") or []
            if grid:
                out.append("\n".join(grid))
        if out:
            return out
    if "completion" in sources:
        for m in rollout.get("completion") or []:
            if m.get("role") in ("user", "tool"):
                c = m.get("content") or ""
                if isinstance(c, list):
                    c = " ".join(str(x) for x in c)
                out.append(c)
    if not out and "prompt" in sources:
        for m in rollout.get("prompt") or []:
            c = m.get("content") or ""
            if isinstance(c, list):
                c = " ".join(str(x) for x in c)
            out.append(c)
    return out


def _final_scout_window_delta(rollout: dict, window: int = 50) -> Optional[float]:
    """Sum of `scout_delta` over the last `window` turns of a local trace.

    Returns None if no trace is available. We deliberately don't try to
    reconstruct scout_delta from the completion stream — that would
    silently hide what triggered the label.
    """
    trace = rollout.get("trace")
    if not trace:
        return None
    deltas = []
    for entry in trace[-window:]:
        # nethack._scout_reward stores per-turn delta on state if present;
        # fall back to differencing cumulative scout_reward.
        if "scout_delta" in entry:
            deltas.append(float(entry["scout_delta"]))
        else:
            sc = entry.get("scout_cumulative")
            if sc is not None:
                deltas.append(float(sc))
    if not deltas:
        return None
    if "scout_delta" in (trace[-1] or {}):
        return float(sum(deltas))
    # Differenced cumulative: last - first
    return float(deltas[-1] - deltas[0])


def classify_failure(rollout: dict) -> str:
    """Classify a non-descending rollout into one of FAILURE_MODES.

    The cascade is deliberately ordered so the most-specific signal wins:
        1. starved           — "starv..." / "died of starvation" in any text
        2. killed_by_monster — "killed by" / "slain by" in any text
        3. turn_budget       — info.is_truncated true (or no death signal
                               and num_turns >= configured cap)
        4. door_block        — saw a door but never opened/kicked one
        5. stuck_no_progress — final-50-turn scout_delta sum ~ 0 (trace
                               available); falls back to "stuck" keyword
                               density in assistant reasoning when no
                               trace
        6. other             — none of the above
    """
    texts = _iter_text(rollout)
    blob = "\n".join(texts[-30:])  # last ~30 turns is enough for death banner
    if _STARVED_PAT.search(blob):
        return "starved"
    if _KILLED_PAT.search(blob):
        return "killed_by_monster"

    info = rollout.get("info") or {}
    if info.get("is_truncated") and not info.get("is_completed"):
        # Truncated without a death message — almost always the turn cap.
        return "turn_budget"

    # door_block: any door seen, no opening/kicking action against it
    saw_door = any(_DOOR_SAW_PAT.search(t) for t in texts)
    opened_door = any(_DOOR_OPENED_PAT.search(t) for t in texts)
    if saw_door and not opened_door:
        # Need a corroborating signal that the agent ended near a door —
        # otherwise a glimpsed door across the map shouldn't trigger this.
        # Use the last 5 turns: was a door still being referenced?
        tail = "\n".join(texts[-5:])
        if _DOOR_SAW_PAT.search(tail):
            return "door_block"

    delta = _final_scout_window_delta(rollout)
    if delta is not None and abs(delta) < 1e-6:
        return "stuck_no_progress"

    # Fallback: count "stuck" keywords across all user msgs when no trace.
    if delta is None:
        stuck_hits = sum(1 for t in texts if "stuck" in t.lower() or "looping" in t.lower())
        if stuck_hits >= 3:
            return "stuck_no_progress"

    return "other"


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _descended(rollout: dict) -> bool:
    return float(rollout.get("descent_reward") or 0.0) >= 1.0


def summarize_eval(samples: list[dict]) -> dict:
    """Aggregate a flat list of rollouts into descent-rate + taxonomy."""
    n = len(samples)
    k = sum(1 for s in samples if _descended(s))
    lo, hi = wilson_ci(k, n)
    scores = [float(s.get("reward") or 0.0) for s in samples]
    avg_score = (sum(scores) / n) if n else 0.0

    # Failure taxonomy: only over non-descending rollouts
    tax: dict[str, int] = {m: 0 for m in FAILURE_MODES}
    per_seed = []
    for s in samples:
        descended = _descended(s)
        mode = None if descended else classify_failure(s)
        if mode is not None:
            tax[mode] += 1
        per_seed.append({
            "seed": s.get("seed") or s.get("example_id"),
            "descended": descended,
            "reward": float(s.get("reward") or 0.0),
            "scout_reward": float(s.get("scout_reward") or 0.0),
            "descent_reward": float(s.get("descent_reward") or 0.0),
            "failure_mode": mode,
        })
    return {
        "n": n,
        "k_descended": k,
        "descent_rate": (k / n) if n else 0.0,
        "ci_lo": lo,
        "ci_hi": hi,
        "avg_score": avg_score,
        "failure_taxonomy": tax,
        "per_seed": per_seed,
    }


# ---------------------------------------------------------------------------
# Sample loading helpers
# ---------------------------------------------------------------------------

def load_hosted_eval_samples(path: str | Path) -> list[dict]:
    """Load samples from a hosted `prime eval get --output json` dump.

    Shape: {evaluation_id, samples: [...], total, ...}. We return the
    samples list as-is so callers can pass it straight to summarize_eval.
    """
    d = json.loads(Path(path).read_text())
    return d.get("samples") or []


def attach_local_traces(samples: list[dict], trace_dir: str | Path) -> list[dict]:
    """Attach NDJSON traces (one file per rollout) onto matching samples.

    The trace filenames are `<seed>_<pid>_<wall>.ndjson` (see
    _write_trace_entry). We match by seed prefix.
    """
    td = Path(trace_dir)
    if not td.is_dir():
        return samples
    files = list(td.glob("*.ndjson"))
    for s in samples:
        seed = s.get("seed") or s.get("example_id")
        if seed is None:
            continue
        for f in files:
            if f.name.startswith(f"{seed}_"):
                try:
                    s["trace"] = [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
                except Exception:
                    pass
                break
    return samples


# ---------------------------------------------------------------------------
# Markdown output
# ---------------------------------------------------------------------------

def _fmt_pct(p: float) -> str:
    return f"{100.0 * p:5.1f}%"


def comparison_table(name_a: str, samples_a: list[dict],
                     name_b: str, samples_b: list[dict]) -> str:
    """Return a markdown comparison of two variants. Side-effect free."""
    sa = summarize_eval(samples_a)
    sb = summarize_eval(samples_b)
    lines: list[str] = []
    lines.append(f"# Descent-rate comparison: `{name_a}` vs `{name_b}`\n")
    lines.append("## Headline\n")
    lines.append("| variant | n | descended | rate | 95% Wilson CI | avg_score |")
    lines.append("|---|---|---|---|---|---|")
    for nm, s in ((name_a, sa), (name_b, sb)):
        lines.append(
            f"| **{nm}** | {s['n']} | {s['k_descended']} | "
            f"{_fmt_pct(s['descent_rate'])} | "
            f"[{_fmt_pct(s['ci_lo'])}, {_fmt_pct(s['ci_hi'])}] | "
            f"{s['avg_score']:.3f} |"
        )

    # Per-seed outcomes side by side
    lines.append("\n## Per-seed outcomes\n")
    lines.append(f"| seed | {name_a} descended | {name_a} mode | {name_b} descended | {name_b} mode |")
    lines.append("|---|---|---|---|---|")
    by_seed_a = {r["seed"]: r for r in sa["per_seed"]}
    by_seed_b = {r["seed"]: r for r in sb["per_seed"]}
    all_seeds = sorted(set(by_seed_a) | set(by_seed_b), key=lambda x: (x is None, x))
    for sd in all_seeds:
        ra = by_seed_a.get(sd) or {}
        rb = by_seed_b.get(sd) or {}
        lines.append(
            f"| {sd} | {ra.get('descended','—')} | {ra.get('failure_mode') or '—'} | "
            f"{rb.get('descended','—')} | {rb.get('failure_mode') or '—'} |"
        )

    # Failure-mode breakdown
    lines.append("\n## Failure-mode breakdown (non-descending rollouts)\n")
    lines.append(f"| mode | {name_a} | {name_b} |")
    lines.append("|---|---|---|")
    for m in FAILURE_MODES:
        lines.append(f"| {m} | {sa['failure_taxonomy'][m]} | {sb['failure_taxonomy'][m]} |")

    return "\n".join(lines) + "\n"
