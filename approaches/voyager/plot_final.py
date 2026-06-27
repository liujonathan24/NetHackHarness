"""Final figures combining the scripted navigation-ceiling sweep (complete, 20
seeds, no LLM) with the partial GLM-5.2 sweep (real cells only). Produces:

  nav_ceiling.png   — P(reach top) & mean floors climbed vs start floor (scripted)
  ceiling_vs_glm.png — scripted ceiling overlaid with the GLM-5.2 cells that ran
  scripted_heatmap.png — per-seed x start-floor reachability grid (scripted)
"""
from __future__ import annotations

import json
import pathlib
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

BASE = pathlib.Path("outputs/curriculum_experiments")
SCRIPTED = BASE / "scripted_nav"
GLM = BASE / "glm5.2_partial"
OUTDIR = BASE / "reverse_curriculum"
OUTDIR.mkdir(parents=True, exist_ok=True)


def scripted_results():
    return json.loads((SCRIPTED / "results.json").read_text())


def glm_by_floor():
    """P(reach top) per start floor from the REAL glm episodes (tools != all-None)."""
    out = {}
    for p in (GLM / "episodes").glob("*.json"):
        e = json.loads(p.read_text())
        ts = e.get("timeseries") or []
        if e.get("llm_error") or (ts and not any(t.get("tool") for t in ts)):
            continue
        out.setdefault(e["start_floor"], []).append(bool(e["reached_top"]))
    return {f: (np.mean(v), len(v)) for f, v in out.items()}


def fig_ceiling(res):
    floors = [2, 3, 4, 5, 6]
    p_top, climbed = [], []
    for f in floors:
        lst = [r for r in res if r["start_floor"] == f]
        p_top.append(np.mean([r["reached_top"] for r in lst]) if lst else np.nan)
        climbed.append(np.mean([r["floors_climbed"] for r in lst]) if lst else np.nan)
    fig, ax1 = plt.subplots(figsize=(8, 5))
    ax1.plot(floors, p_top, "o-", color="tab:blue", lw=2, ms=9, label="P(reach floor 1)")
    ax1.set_xlabel("start curriculum floor  (deeper = farther from goal)")
    ax1.set_ylabel("P(reach floor 1)", color="tab:blue"); ax1.set_ylim(-0.05, 1.05)
    ax1.tick_params(axis="y", labelcolor="tab:blue")
    ax1.axvline(3.5, ls=":", color="gray")
    ax1.text(3.55, 0.7, "floor 4→3:\nGehennom→DoD\ncross-branch jump", fontsize=8, color="gray")
    ax2 = ax1.twinx()
    ax2.plot(floors, climbed, "s--", color="tab:red", lw=1.5, ms=7, label="mean floors climbed")
    ax2.set_ylabel("mean floors climbed", color="tab:red"); ax2.tick_params(axis="y", labelcolor="tab:red")
    ax2.set_ylim(0, max(1.0, np.nanmax(climbed) * 1.3))
    ax1.set_title("Navigation ceiling: scripted greedy-climb policy\n(20 seeds, legal primitives, NO LLM)")
    ln = ax1.get_lines() + ax2.get_lines()
    ax1.legend(ln, [l.get_label() for l in ln], loc="upper right", fontsize=9)
    fig.tight_layout(); fig.savefig(OUTDIR / "nav_ceiling.png", dpi=130); plt.close(fig)


def fig_ceiling_vs_glm(res):
    floors = [2, 3, 4, 5, 6]
    scr = [np.mean([r["reached_top"] for r in res if r["start_floor"] == f]) for f in floors]
    glm = glm_by_floor()
    gx = [f for f in floors if f in glm]
    gy = [glm[f][0] for f in gx]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(floors, scr, "o-", color="tab:blue", lw=2, ms=9,
            label="scripted greedy-nav (20 seeds, complete)")
    ax.plot(gx, gy, "D-", color="tab:green", lw=2, ms=10,
            label="GLM-5.2 agent (4 seeds, real cells)")
    for f in floors:
        if f not in glm:
            ax.scatter([f], [0], marker="x", s=90, color="darkred", zorder=5)
    ax.text(5.5, 0.04, "GLM deep cells:\nnot run (Prime 402)", fontsize=8,
            color="darkred", ha="right")
    ax.axvline(3.5, ls=":", color="gray")
    ax.set_xlabel("start curriculum floor  (deeper = farther from goal)")
    ax.set_ylabel("P(reach floor 1)"); ax.set_ylim(-0.05, 1.05)
    ax.set_title("Climb reachability vs. start depth\nscripted ceiling vs. GLM-5.2 agent")
    ax.legend(loc="upper right", fontsize=9)
    fig.tight_layout(); fig.savefig(OUTDIR / "ceiling_vs_glm.png", dpi=130); plt.close(fig)


def fig_heatmap(res):
    seeds = sorted({r["seed"] for r in res})
    floors = [2, 3, 4, 5, 6]
    grid = np.full((len(floors), len(seeds)), np.nan)
    for i, f in enumerate(floors):
        for j, s in enumerate(seeds):
            m = [r for r in res if r["start_floor"] == f and r["seed"] == s]
            if m:
                grid[i, j] = m[0]["floors_climbed"]
    fig, ax = plt.subplots(figsize=(0.46 * len(seeds) + 2, 0.6 * len(floors) + 2))
    im = ax.imshow(grid, cmap="viridis", aspect="auto", vmin=0, vmax=max(1, np.nanmax(grid)))
    ax.set_xticks(range(len(seeds))); ax.set_xticklabels(seeds, fontsize=7)
    ax.set_yticks(range(len(floors))); ax.set_yticklabels([f"from {f}" for f in floors])
    ax.set_xlabel("seed"); ax.set_title("Scripted floors-climbed per seed × start floor\n(bright = climbed; dark = stuck at start)")
    fig.colorbar(im, ax=ax, label="floors climbed")
    fig.tight_layout(); fig.savefig(OUTDIR / "scripted_heatmap.png", dpi=130); plt.close(fig)


def main():
    res = scripted_results()
    fig_ceiling(res); fig_ceiling_vs_glm(res); fig_heatmap(res)
    glm = glm_by_floor()
    print("GLM real P(top) by floor:", {f: (round(v[0], 3), v[1]) for f, v in glm.items()})
    print(f"wrote nav_ceiling.png, ceiling_vs_glm.png, scripted_heatmap.png to {OUTDIR}")


if __name__ == "__main__":
    main()
