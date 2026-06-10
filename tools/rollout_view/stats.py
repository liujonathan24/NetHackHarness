"""Post-hoc time-series metrics over saved rollout traces.

Reads the per-turn NDJSON traces (written by `_write_trace_entry`) and derives
time series WITHOUT touching the live env loop. Metrics are computed at read
time by mapping functions over each turn's saved observation, so you can define
custom obs/metrics as plain Python and apply them to any already-saved run.

A "turn record" is a dict: {turn, status:{...parsed...}, text, raw_grid, raw}.
A "metric" is a function record -> float|None; `series()` maps it over a run.

Built-in metrics parse the rendered STATUS block (robust across trace formats);
register your own with `register_metric(name, fn)` to derive any custom obs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Optional

# --- parse the harness STATUS block out of a turn's rendered observation text ---
# e.g. "=== STATUS ===\nHP: 14/14  AC: 4  Dlvl: 1  Turn: 1  XP: 1  $: 0  Pos: (26,5)  Hunger: Fainting"
_PATS = {
    "hp": re.compile(r"HP:\s*(\d+)\s*/\s*\d+"),
    "max_hp": re.compile(r"HP:\s*\d+\s*/\s*(\d+)"),
    "ac": re.compile(r"AC:\s*(-?\d+)"),
    "dlvl": re.compile(r"Dlvl:\s*(\d+)"),
    "ingame_turn": re.compile(r"Turn:\s*(\d+)"),
    "xp": re.compile(r"XP:\s*(\d+)"),
    "gold": re.compile(r"\$:\s*(\d+)"),
}
_HUNGER_RE = re.compile(r"Hunger:\s*(\w+)")
_HUNGER_LEVEL = {  # ordinal so it can be charted
    "Satiated": -1, "Normal": 0, "Hungry": 1, "Weak": 2, "Fainting": 3,
    "Fainted": 4, "Starved": 5,
}
_KILL_RE = re.compile(r"You kill|You destroy(?:ed)? the|You smite", re.I)
_DEATH_RE = re.compile(
    r"you died|you were killed|killed by|starved to death|petrified|turned to stone"
    r"|do you want your possessions identified", re.I)


def parse_status(text: str) -> dict:
    """Extract scalar status fields from a turn's rendered observation text."""
    out: dict = {}
    for name, pat in _PATS.items():
        m = pat.search(text)
        if m:
            out[name] = int(m.group(1))
    h = _HUNGER_RE.search(text)
    if h:
        out["hunger"] = _HUNGER_LEVEL.get(h.group(1))
    return out


def _turn_text(rec: dict) -> str:
    """The rendered observation text for a raw trace line (handles both the
    structured `status` dict format and the rendered-text format)."""
    for key in ("rendered_user_message", "rendered_user_content"):
        v = rec.get(key)
        if isinstance(v, str):
            return v
        if isinstance(v, list):  # multimodal [{image_url}, {text}]
            return " ".join(p.get("text", "") for p in v if isinstance(p, dict))
    return ""


def load_trace(path) -> list[dict]:
    """Load one NDJSON trace into a list of turn records (sorted by turn)."""
    recs: list[dict] = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        text = _turn_text(raw)
        status = dict(raw.get("status") or {})
        # prefer explicit fields, else parse from the rendered text
        if not status:
            status = parse_status(text)
        if raw.get("dlvl") is not None:
            status.setdefault("dlvl", raw.get("dlvl"))
        if raw.get("hp") is not None:
            status.setdefault("hp", raw.get("hp"))
        recs.append({
            "turn": int(raw.get("turn", len(recs))),
            "status": status,
            "text": text,
            "raw_grid": raw.get("raw_grid"),
            "raw": raw,
        })
    recs.sort(key=lambda r: r["turn"])
    return recs


def load_results_jsonl(path) -> list[list[dict]]:
    """Each row of a verifiers results.jsonl is ONE rollout; return a list of runs,
    each a list of turn records parsed from that rollout's observation messages.
    Lets the dashboard chart eval runs that saved results.jsonl (not trace_dir)."""
    runs: list[list[dict]] = []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        recs, t = [], 0
        for m in row.get("completion") or []:
            if m.get("role") not in ("user", "tool"):
                continue
            c = m.get("content")
            text = c if isinstance(c, str) else " ".join(
                p.get("text", "") for p in (c or []) if isinstance(p, dict))
            recs.append({"turn": t, "status": parse_status(text), "text": text,
                         "raw_grid": None, "raw": {}})
            t += 1
        if recs:
            runs.append(recs)
    return runs


# ---- metric registry: record -> float|None ----
def _stat(name) -> Callable[[dict], Optional[float]]:
    return lambda rec: rec["status"].get(name)


BUILTIN_METRICS: dict[str, Callable[[dict], Optional[float]]] = {
    "dlvl": _stat("dlvl"),
    "hp": _stat("hp"),
    "max_hp": _stat("max_hp"),
    "hp_frac": lambda r: (r["status"].get("hp") / r["status"]["max_hp"]
                          if r["status"].get("max_hp") else None),
    "xp": _stat("xp"),
    "gold": _stat("gold"),
    "ac": _stat("ac"),
    "hunger": _stat("hunger"),
    "ingame_turn": _stat("ingame_turn"),
    "kills_cum": None,  # filled below (stateful, needs the whole series)
}

_CUSTOM_METRICS: dict[str, Callable[[dict], Optional[float]]] = {}


def register_metric(name: str, fn: Callable[[dict], Optional[float]]) -> None:
    """Register a custom obs/metric: fn(turn_record) -> float|None. The record
    exposes status (parsed), text (rendered obs), and raw_grid — derive anything."""
    _CUSTOM_METRICS[name] = fn


def metric_names() -> list[str]:
    return sorted(set(BUILTIN_METRICS) | set(_CUSTOM_METRICS))


def series(records: list[dict], name: str) -> list[tuple[int, float]]:
    """Time series [(turn, value), ...] for `name` over one run's records."""
    if name == "kills_cum":
        out, c = [], 0
        for r in records:
            c += len(_KILL_RE.findall(r["text"]))
            out.append((r["turn"], float(c)))
        return out
    fn = _CUSTOM_METRICS.get(name) or BUILTIN_METRICS.get(name)
    if fn is None:
        raise KeyError(f"unknown metric {name!r}; have {metric_names()}")
    out = []
    for r in records:
        v = fn(r)
        if v is not None:
            out.append((r["turn"], float(v)))
    return out


def run_summary(records: list[dict]) -> dict:
    """One-line summary of a run for the cross-run aggregate table."""
    dl = [v for _, v in series(records, "dlvl")]
    xp = [v for _, v in series(records, "xp")]
    hp = [v for _, v in series(records, "hp")]
    kills = series(records, "kills_cum")
    died = any(_DEATH_RE.search(r["text"]) for r in records)
    return {
        "n_turns": len(records),
        "max_dlvl": max(dl) if dl else 1,
        "max_xp": max(xp) if xp else 1,
        "min_hp": min(hp) if hp else None,
        "kills": int(kills[-1][1]) if kills else 0,
        "died": died,
    }


def aggregate(runs: list[list[dict]]) -> dict:
    """Cross-run aggregate stats from a list of runs' records."""
    sums = [run_summary(r) for r in runs if r]
    n = len(sums) or 1
    maxd = [s["max_dlvl"] for s in sums]
    return {
        "n_runs": len(sums),
        "mean_max_dlvl": sum(maxd) / n,
        "mean_max_xp": sum(s["max_xp"] for s in sums) / n,
        "mean_kills": sum(s["kills"] for s in sums) / n,
        "death_rate": sum(1 for s in sums if s["died"]) / n,
        "reached_dlvl3": sum(1 for s in sums if s["max_dlvl"] >= 3),
        "summaries": sums,
    }
