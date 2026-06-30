"""Analyze the reverse-curriculum sweep: plots + a timeline + a stats table.

Reads the per-episode JSON files written by reverse_curriculum_sweep.py (each has
the full per-turn timeseries) and produces, under ``--out``:

  1. reachability.png   — success rate (reached floor 1) and mean floors-climbed
                          vs start floor, with the full_tour baseline marked.
  2. heatmap.png        — condition x seed grid of reached_top / floors_climbed.
  3. trajectories.png   — floor-vs-turn climb trajectories per condition.
  4. timeline.png       — Gantt-style wall-clock timeline of episode runs.
  5. summary.json/.md   — per-condition aggregate stats.

Robust to partial data (run it on the validation wave too).
"""
from __future__ import annotations

import argparse
import json
import pathlib
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Canonical condition order (start depth ascending; full_tour last as baseline).
ORDER = ["climb_from_2", "climb_from_3", "climb_from_4", "climb_from_5",
         "climb_from_6", "full_tour"]
START_FLOOR = {"climb_from_2": 2, "climb_from_3": 3, "climb_from_4": 4,
               "climb_from_5": 5, "climb_from_6": 6, "full_tour": 1}


def _is_valid(e: dict) -> bool:
    """Drop episodes that never got real LLM responses: a hard llm_error, or a
    timeseries where every tool is None (the all-no-op signature of an episode
    whose every call failed — e.g. Prime returning 402 out of credits)."""
    if e.get("llm_error"):
        return False
    ts = e.get("timeseries") or []
    if ts and not any(t.get("tool") is not None for t in ts):
        return False
    return True


def load_episodes(out: pathlib.Path) -> list[dict]:
    eps, dropped = [], 0
    for p in sorted((out / "episodes").glob("*.json")):
        try:
            e = json.loads(p.read_text())
        except Exception:
            continue
        if _is_valid(e):
            eps.append(e)
        else:
            dropped += 1
    if dropped:
        print(f"[analyze] dropped {dropped} invalid (no-LLM / errored) episodes")
    return eps


def aggregate(eps: list[dict]) -> dict:
    by_cond: dict[str, list[dict]] = defaultdict(list)
    for e in eps:
        if "condition" in e and "reached_top" in e:
            by_cond[e["condition"]].append(e)
    summary = {}
    for cond, lst in by_cond.items():
        top = [bool(e["reached_top"]) for e in lst]
        climbed = [int(e.get("floors_climbed", 0)) for e in lst]
        deepest = [int(e.get("deepest_floor", 0)) for e in lst]
        died = [bool(e.get("died", False)) for e in lst]
        summary[cond] = {
            "n": len(lst),
            "start_floor": START_FLOOR.get(cond),
            "success_rate": round(float(np.mean(top)), 3) if top else None,
            "mean_floors_climbed": round(float(np.mean(climbed)), 2) if climbed else None,
            "max_floors_climbed": int(np.max(climbed)) if climbed else None,
            "mean_deepest": round(float(np.mean(deepest)), 2) if deepest else None,
            "death_rate": round(float(np.mean(died)), 3) if died else None,
            "mean_wall_s": round(float(np.mean([e.get("wall_s", 0) for e in lst])), 1),
        }
    return summary


def plot_reachability(summary: dict, out: pathlib.Path):
    climbs = [c for c in ORDER if c.startswith("climb_") and c in summary]
    if not climbs:
        return
    xs = [START_FLOOR[c] for c in climbs]
    succ = [summary[c]["success_rate"] for c in climbs]
    climbed = [summary[c]["mean_floors_climbed"] for c in climbs]
    fig, ax1 = plt.subplots(figsize=(8, 5))
    ax1.plot(xs, succ, "o-", color="tab:blue", lw=2, ms=9,
             label="P(reach floor 1)")
    ax1.set_xlabel("start curriculum floor  (deeper = farther from the goal)")
    ax1.set_ylabel("success rate  P(reach floor 1)", color="tab:blue")
    ax1.set_ylim(-0.05, 1.05)
    ax1.tick_params(axis="y", labelcolor="tab:blue")
    ax1.axvline(3.5, ls=":", color="gray")
    ax1.text(3.55, 0.5, "floor 4->3 = Gehennom->DoD\ncross-branch jump-up",
             fontsize=8, color="gray", va="center")
    ax2 = ax1.twinx()
    ax2.plot(xs, climbed, "s--", color="tab:red", lw=1.5, ms=7,
             label="mean floors climbed")
    ax2.set_ylabel("mean floors climbed", color="tab:red")
    ax2.tick_params(axis="y", labelcolor="tab:red")
    if "full_tour" in summary and summary["full_tour"]["success_rate"] is not None:
        ax1.axhline(summary["full_tour"]["success_rate"], ls="-.", color="black",
                    lw=1, label=f"full_tour P(top)={summary['full_tour']['success_rate']}")
    ax1.set_title("Climb reachability vs. start depth\n"
                  "(legal primitives only — no ascend/descend skill)")
    lines = ax1.get_lines() + ax2.get_lines()
    ax1.legend(lines, [l.get_label() for l in lines], loc="center left", fontsize=8)
    fig.tight_layout(); fig.savefig(out / "reachability.png", dpi=130)
    plt.close(fig)


def plot_heatmap(eps: list[dict], out: pathlib.Path):
    conds = [c for c in ORDER if any(e.get("condition") == c for e in eps)]
    seeds = sorted({e["seed"] for e in eps if "seed" in e})
    if not conds or not seeds:
        return
    # average floors_climbed per (cond, seed)
    grid = np.full((len(conds), len(seeds)), np.nan)
    for i, c in enumerate(conds):
        for j, s in enumerate(seeds):
            vals = [e["floors_climbed"] for e in eps
                    if e.get("condition") == c and e.get("seed") == s
                    and "floors_climbed" in e]
            if vals:
                grid[i, j] = float(np.mean(vals))
    fig, ax = plt.subplots(figsize=(1.4 * len(seeds) + 2, 0.7 * len(conds) + 2))
    im = ax.imshow(grid, cmap="viridis", aspect="auto")
    ax.set_xticks(range(len(seeds))); ax.set_xticklabels([f"seed {s}" for s in seeds])
    ax.set_yticks(range(len(conds))); ax.set_yticklabels(conds)
    for i in range(len(conds)):
        for j in range(len(seeds)):
            if not np.isnan(grid[i, j]):
                ax.text(j, i, f"{grid[i, j]:.1f}", ha="center", va="center",
                        color="w", fontsize=9)
    ax.set_title("Mean floors climbed  (condition x seed)")
    fig.colorbar(im, ax=ax, label="floors climbed")
    fig.tight_layout(); fig.savefig(out / "heatmap.png", dpi=130)
    plt.close(fig)


def plot_trajectories(eps: list[dict], out: pathlib.Path):
    conds = [c for c in ORDER if any(e.get("condition") == c for e in eps)]
    if not conds:
        return
    n = len(conds)
    fig, axes = plt.subplots(1, n, figsize=(3 * n, 3.4), sharey=True)
    if n == 1:
        axes = [axes]
    for ax, c in zip(axes, conds):
        for e in eps:
            if e.get("condition") != c or "timeseries" not in e:
                continue
            ts = [t for t in e["timeseries"] if t.get("floor", 0) > 0]
            if not ts:
                continue
            turns = [t["turn"] for t in ts]
            floors = [t["floor"] for t in ts]
            ax.plot(turns, floors, lw=1, alpha=0.7)
        ax.axhline(1, ls=":", color="green", lw=1)
        ax.set_title(c, fontsize=9)
        ax.set_xlabel("turn"); ax.set_ylim(0.5, 6.5)
        ax.invert_yaxis()  # floor 1 (goal) at top
    axes[0].set_ylabel("curriculum floor\n(1=top goal)")
    fig.suptitle("Floor trajectories (each line = one episode; goal = reach floor 1 at top)")
    fig.tight_layout(); fig.savefig(out / "trajectories.png", dpi=130)
    plt.close(fig)


def plot_timeline(eps: list[dict], out: pathlib.Path):
    """Gantt timeline of episode runs, reconstructed from each episode file's
    completion mtime (write time) minus its measured wall_s duration."""
    rows = []
    for p in sorted((out / "episodes").glob("*.json")):
        try:
            e = json.loads(p.read_text())
        except Exception:
            continue
        end = p.stat().st_mtime
        dur = float(e.get("wall_s", 0.0))
        rows.append((end - dur, end, e.get("condition", "?"),
                     e.get("seed", "?"), bool(e.get("reached_top", False))))
    if not rows:
        return
    t0 = min(r[0] for r in rows)
    rows.sort(key=lambda r: r[0])
    cond_color = {c: plt.cm.tab10(i) for i, c in enumerate(ORDER)}
    fig, ax = plt.subplots(figsize=(11, 0.32 * len(rows) + 1.5))
    for y, (st, en, cond, seed, top) in enumerate(rows):
        ax.barh(y, (en - st) / 60.0, left=(st - t0) / 60.0, height=0.7,
                color=cond_color.get(cond, "gray"),
                edgecolor="black" if top else "none", lw=1.5)
        ax.text((en - t0) / 60.0 + 0.3, y, f"{cond} s{seed}{' ✓' if top else ''}",
                va="center", fontsize=6)
    ax.set_xlabel("minutes since sweep start")
    ax.set_yticks([])
    ax.set_title("Episode run timeline  (bold outline = reached floor 1)")
    handles = [plt.Rectangle((0, 0), 1, 1, color=cond_color[c]) for c in ORDER
               if any(r[2] == c for r in rows)]
    labels = [c for c in ORDER if any(r[2] == c for r in rows)]
    ax.legend(handles, labels, fontsize=7, ncol=3, loc="lower right")
    fig.tight_layout(); fig.savefig(out / "timeline.png", dpi=130)
    plt.close(fig)


def write_summary(summary: dict, eps: list[dict], out: pathlib.Path):
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
    lines = ["# Reverse-curriculum sweep — summary\n",
             f"Episodes analyzed: {len(eps)}\n",
             "| condition | start floor | n | P(reach top) | mean climbed | max climbed | death rate | mean wall (s) |",
             "|---|---|---|---|---|---|---|---|"]
    for c in ORDER:
        if c not in summary:
            continue
        s = summary[c]
        lines.append(f"| {c} | {s['start_floor']} | {s['n']} | {s['success_rate']} | "
                     f"{s['mean_floors_climbed']} | {s['max_floors_climbed']} | "
                     f"{s['death_rate']} | {s['mean_wall_s']} |")
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="outputs/curriculum_experiments/reverse_curriculum")
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    eps = load_episodes(out)
    if not eps:
        print(f"no episodes found under {out}/episodes")
        return
    summary = aggregate(eps)
    plot_reachability(summary, out)
    plot_heatmap(eps, out)
    plot_trajectories(eps, out)
    plot_timeline(eps, out)
    write_summary(summary, eps, out)
    print(f"\nwrote plots + summary under {out}")


if __name__ == "__main__":
    main()
