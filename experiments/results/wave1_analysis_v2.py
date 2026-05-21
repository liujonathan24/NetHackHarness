"""Wave-1 analysis V2 — corrected reward decomposition.

Discovery (via prime eval samples): avg_score is the UNWEIGHTED SUM of
reward-function values, not the rubric-weighted total. Each sample carries
the four component fields directly:
    scout_reward (raw, 0–1)
    descent_reward (count of dlvl transitions)
    success_reward (0/1 — corridor_explore milestone fired)
    ascension_reward (0/1)

This changes the interpretation of N seeds 22 and 23 entirely:
    N22: reward 2.155 = scout 0.155 + descent 1 + success 1
    N23: reward 2.257 = scout 0.257 + descent 1 + success 1
Both N rollouts **DESCENDED + HIT THE SUCCESS MILESTONE**. B1 never did.

Input: pre-pulled `prime eval samples` JSONs at /tmp/{N22,N23,B1_22,B1_24}_samples.json
       plus the per-seed score table from the wave-1 listings.
"""
from __future__ import annotations
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

# Per-seed scores by variant (avg_score, unweighted sum). Same as v1.
QWEN_SCORES = {
    "B":  [0.034, 0.066, 0.046, 0.081, 0.051],
    "B0": [0.078, 0.127, 0.102],
    "B1": [0.048, 0.054, 0.115, 0.109],
    "G":  [0.095],
    "N":  [2.155, 2.257, 0.039, 0.097],
    "P":  [0.100, 0.100, 0.108],
    "R":  [0.064, 0.198, 0.107, 0.076],
}

# Per-seed reward decomposition where we have it (from prime eval samples).
# (scout, descent_count, success_flag, ascend_flag).
N_DECOMP = {
    22: (0.155, 1, 1, 0),
    23: (0.257, 1, 1, 0),
    # 25 and 26 we don't have samples for, but reward<0.1 means scout-only.
}
B1_DECOMP = {
    22: (0.048, 0, 0, 0),
    24: (0.115, 0, 0, 0),
    # 23, 26 similar — pure scout, no descent.
}


def fmt(v): return f"{v:.3f}" if v is not None else "—"


def cohen_d(a, b):
    if len(a) < 2 or len(b) < 2:
        return float("nan")
    sd_pool = np.sqrt((np.var(a, ddof=1) + np.var(b, ddof=1)) / 2)
    if sd_pool == 0:
        return float("nan")
    return (np.mean(b) - np.mean(a)) / sd_pool


def main():
    variants = sorted(QWEN_SCORES.keys(), key=lambda v: -np.mean(QWEN_SCORES[v]))

    # ---------- corrected component decomposition plot ----------
    # Show per-seed components, color-coded.
    fig, ax = plt.subplots(figsize=(10, 5.5))
    # Build a per-seed stacked-bar layout. Each variant gets a horizontal slot
    # of width 1; within it, n seeds occupy sub-slots.
    bar_w = 0.15
    legend_done = False
    for vi, v in enumerate(variants):
        n = len(QWEN_SCORES[v])
        xs = vi + (np.arange(n) - (n - 1) / 2) * bar_w * 1.05
        scores = QWEN_SCORES[v]
        # Decompose where we know exactly, else assume scout-only.
        comps = []
        for i, sc in enumerate(scores):
            if v == "N":
                seed = 22 + i  # 22..26, completed subset
                if seed in N_DECOMP:
                    comps.append(N_DECOMP[seed])
                else:
                    comps.append((sc, 0, 0, 0))
            elif v == "B1":
                seed = 22 + i
                if seed in B1_DECOMP:
                    comps.append(B1_DECOMP[seed])
                else:
                    comps.append((sc, 0, 0, 0))
            else:
                # No descent/success observed across any sampled seeds; treat as scout-only.
                comps.append((sc, 0, 0, 0))
        scout = np.array([c[0] for c in comps])
        desc = np.array([c[1] for c in comps]).astype(float)  # count, not weighted
        succ = np.array([c[2] for c in comps]).astype(float)
        ax.bar(xs, scout, bar_w, label="scout (0–1)" if not legend_done else None,
               color="#bbbbff", edgecolor="black", linewidth=0.4)
        ax.bar(xs, desc, bar_w, bottom=scout,
               label="descent (1 per dlvl)" if not legend_done else None,
               color="#66cc66", edgecolor="black", linewidth=0.4)
        ax.bar(xs, succ, bar_w, bottom=scout + desc,
               label="success milestone (+1)" if not legend_done else None,
               color="#ffaa55", edgecolor="black", linewidth=0.4)
        legend_done = True

    ax.set_xticks(range(len(variants)))
    ax.set_xticklabels(variants, fontsize=12, fontweight="bold")
    ax.set_ylabel("avg_score (UNWEIGHTED reward-fn sum)", fontsize=10)
    ax.set_title("Wave-1 corrected decomposition: each bar = one seed\n"
                 "N seeds 22, 23 actually DESCENDED + COMPLETED corridor_explore", fontsize=11)
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    p = OUT_DIR / "wave1_decomp_v2.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    print(f"wrote {p}")

    # ---------- success-rate bar (binary: did the rollout finish corridor_explore?) ----------
    success_rates = {}
    for v in variants:
        if v == "N":
            success_rates[v] = (sum(N_DECOMP.get(22 + i, (0, 0, 0, 0))[2] for i in range(len(QWEN_SCORES[v]))) / len(QWEN_SCORES[v]))
        elif v == "B1":
            success_rates[v] = 0.0  # confirmed via samples
        else:
            success_rates[v] = 0.0  # scores all <1; can't have hit success
    fig, ax = plt.subplots(figsize=(8, 4.5))
    xs = range(len(variants))
    ax.bar(xs, [success_rates[v] for v in variants],
           color=["seagreen" if v == "N" else "lightgray" for v in variants],
           edgecolor="black")
    for i, v in enumerate(variants):
        rate = success_rates[v]
        ax.text(i, rate + 0.02, f"{rate*100:.0f}%", ha="center", fontsize=10)
    ax.set_xticks(xs)
    ax.set_xticklabels(variants, fontsize=12, fontweight="bold")
    ax.set_ylabel("success_reward rate (fraction of seeds completing corridor_explore)")
    ax.set_title("Wave-1 binary success rate per variant", fontsize=11)
    ax.set_ylim(0, 1.0)
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    p2 = OUT_DIR / "wave1_success_rate.png"
    fig.savefig(p2, dpi=120)
    plt.close(fig)
    print(f"wrote {p2}")


if __name__ == "__main__":
    main()
