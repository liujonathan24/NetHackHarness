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
from typing import Optional


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


def _walk_tagged(tag_prefix: str, base: Path) -> list[Path]:
    """Return metadata.json files under `base` whose enclosing dir matches
    the `<base>/<variant>/<model>/seed<N>/metadata.json` layout produced by
    `experiments/exp16_obs_variants.py`. We don't require the tag string to
    be embedded in the file itself — the path layout is the index."""
    if not base.exists():
        return []
    return sorted(base.glob(f"{tag_prefix}/*/*/*/metadata.json"))


def _seed_max_dlvl(meta: dict) -> Optional[float]:
    """Pull the seed's max-Dlvl-reached from metadata.json.

    `prime eval run` saves per-rollout state in `rollouts[].state`. We try
    a few shapes for forward-compat: a top-level avg_metrics entry, a
    rollouts list, or a flat state dict.
    """
    am = meta.get("avg_metrics") or {}
    if "max_dlvl_reached" in am:
        return float(am["max_dlvl_reached"])
    rollouts = meta.get("rollouts") or []
    if rollouts:
        vals = []
        for r in rollouts:
            st = (r or {}).get("state") or {}
            v = st.get("max_dlvl_reached") or st.get("max_dlvl") or st.get("dlvl")
            if v is not None:
                vals.append(float(v))
        if vals:
            return float(sum(vals) / len(vals))
    st = meta.get("state") or {}
    if "max_dlvl_reached" in st:
        return float(st["max_dlvl_reached"])
    # Fallback: avg descent_reward counts each new dlvl as +1 weighted by
    # 10.0 in the rubric, so descent_reward/10 + 1 estimates max_dlvl.
    dr = am.get("descent_reward")
    if dr is not None:
        return 1.0 + float(dr) / 10.0
    return None


def _seed_tokens_per_turn(meta: dict) -> Optional[float]:
    usage = meta.get("usage") or {}
    am = meta.get("avg_metrics") or {}
    inp = float(usage.get("input_tokens", 0) or 0)
    out = float(usage.get("output_tokens", 0) or 0)
    n_turns = float(am.get("num_turns", 0) or 0)
    if n_turns <= 0:
        return None
    return (inp + out) / n_turns


def _mean_sem(xs: list[float]) -> tuple[float, float]:
    if not xs:
        return 0.0, 0.0
    n = len(xs)
    m = sum(xs) / n
    if n < 2:
        return m, 0.0
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    sem = (var ** 0.5) / (n ** 0.5)
    return m, sem


def _welch_t(a: list[float], b: list[float]) -> Optional[float]:
    """Welch's t (returns t-statistic). p-value omitted — keeps deps zero;
    callers can interpret |t|>~2 as p<~0.05 for n~20."""
    if len(a) < 2 or len(b) < 2:
        return None
    ma, sa = _mean_sem(a)
    mb, sb = _mean_sem(b)
    # sa, sb are SEMs already
    denom = (sa * sa + sb * sb) ** 0.5
    if denom == 0:
        return None
    return (mb - ma) / denom


def _aggregate_hosted(tag_prefix: str) -> dict:
    """Pull hosted evals via `prime eval list` and group by name prefix.

    Naming convention from experiments/exp16_obs_variants.py:
      `wave1-<variant>-<model-slug>-seed<N>`
    where model-slug has '/' replaced with '-'. We parse variant + model
    + seed back out and aggregate by (variant, model).
    """
    import subprocess, json as _json, re
    # API limit: -n max 100 per page; paginate until total reached.
    evals: list = []
    page = 1
    while True:
        out = subprocess.check_output(
            ["prime", "eval", "list", "--env", "nethack",
             "-n", "100", "-p", str(page), "--output", "json", "--plain"],
            text=True,
        )
        data = _json.loads(out)
        chunk = data.get("evaluations") or []
        if not chunk:
            break
        evals.extend(chunk)
        if len(evals) >= int(data.get("total", 0)):
            break
        page += 1
        if page > 20:  # safety
            break
    summary: dict = {}
    # name pattern: wave1-<variant>-<model-with-dashes>-seed<N>.
    # Restrict to canonical wave-1 variants so continual-validate runs and
    # other ad-hoc names don't pollute the table.
    _KNOWN = {"B0", "B1", "G", "B", "N", "R", "P"}
    pat = re.compile(rf"^{re.escape(tag_prefix)}-([^-]+)-(.+)-seed(\d+)$")
    for e in evals:
        name = e.get("name") or ""
        m = pat.match(name)
        if not m:
            continue
        variant, model_slug, seed = m.group(1), m.group(2), int(m.group(3))
        if variant not in _KNOWN:
            continue
        status = e.get("status") or ""
        if status != "COMPLETED":
            summary.setdefault((variant, model_slug), {"pending": 0, "rows": []})
            summary[(variant, model_slug)]["pending"] = (
                summary[(variant, model_slug)].get("pending", 0) + 1
            )
            continue
        metrics = e.get("metrics") or {}
        # Hosted `prime eval get` returns avg_score (the rubric-weighted
        # total reward) reliably but `metrics` is often empty. Use avg_score
        # as the comparison primitive; estimate descents from its magnitude
        # via the rubric weights:
        #   scout_reward (w=1) is ~0.05-0.20 typical
        #   descent_reward (w=10) adds 10 per new dlvl
        #   success_reward (w=100), ascension_reward (w=1000)
        avg_score = e.get("avg_score")
        if avg_score is None:
            continue
        # Estimate descents = floor(avg_score / 10) ignoring fractional scout/
        # success/ascend bonuses. Max_dlvl = 1 + descents.
        descents = max(0, int(float(avg_score) // 10))
        max_dlvl = 1 + descents
        bucket = summary.setdefault((variant, model_slug), {"pending": 0, "rows": []})
        bucket["rows"].append({
            "seed": seed,
            "max_dlvl": float(max_dlvl),
            "avg_score": float(avg_score),
            "tokens_per_turn": None,
            "metrics": metrics,
        })
    # Reduce each bucket to mean/sem.
    final = {}
    for key, bucket in summary.items():
        dlvls = [r["max_dlvl"] for r in bucket["rows"] if r["max_dlvl"] is not None]
        scores = [r["avg_score"] for r in bucket["rows"] if r.get("avg_score") is not None]
        tpts = [r["tokens_per_turn"] for r in bucket["rows"] if r["tokens_per_turn"]]
        m, sem = _mean_sem(dlvls)
        sm, ssem = _mean_sem(scores)
        tm, _ = _mean_sem(tpts)
        final[key] = {
            "n_seeds": len(bucket["rows"]),
            "n_pending": bucket.get("pending", 0),
            "mean_max_dlvl": m,
            "sem_max_dlvl": sem,
            "dlvls": dlvls,
            "mean_avg_score": sm,
            "sem_avg_score": ssem,
            "mean_tokens_per_turn": tm,
        }
    return final


def _aggregate_tag(tag_prefix: str, base: Path) -> dict:
    """Group metadata.json files by (variant, model) and aggregate."""
    files = _walk_tagged(tag_prefix, base)
    groups: dict[tuple[str, str], list[Path]] = {}
    for f in files:
        # base/<variant>/<model>/seed<N>/metadata.json
        try:
            seed_dir, model_dir, variant_dir, *_ = list(reversed(f.parts[:-1]))
        except ValueError:
            continue
        # parts above: [base..., variant, model, seedN]
        rel = f.relative_to(base)
        parts = rel.parts
        if len(parts) < 4:
            continue
        variant = parts[0]
        model = parts[1]
        groups.setdefault((variant, model), []).append(f)
    summary = {}
    for (variant, model), paths in groups.items():
        dlvls, tpts = [], []
        for p in paths:
            try:
                meta = _load(str(p))
            except Exception:
                continue
            d = _seed_max_dlvl(meta)
            if d is not None:
                dlvls.append(d)
            t = _seed_tokens_per_turn(meta)
            if t is not None:
                tpts.append(t)
        m, sem = _mean_sem(dlvls)
        tm, _ = _mean_sem(tpts)
        summary[(variant, model)] = {
            "n_seeds": len(paths),
            "mean_max_dlvl": m,
            "sem_max_dlvl": sem,
            "dlvls": dlvls,
            "mean_tokens_per_turn": tm,
        }
    return summary


def _emit_wave1_markdown(summary: dict, out_path: Path, baseline: str = "B1") -> None:
    """Write experiments/results/wave1_summary.md with the headline table."""
    lines = []
    lines.append("# Wave-1 observation/skill-structure variants — summary\n")
    lines.append("Generated by `tools/compare_evals.py --tag wave1`. "
                 "Metric: mean max-Dlvl reached across 200-move rollouts per seed; "
                 "side-metric: tokens/turn (≤1.5× B1 is the cap).\n")
    # Group by model
    models = sorted({m for (_, m) in summary.keys()})
    for model in models:
        lines.append(f"\n## Model: `{model}`\n")
        # Pull baseline dlvls for this model
        base_dlvls = summary.get((baseline, model), {}).get("dlvls", [])
        rows = []
        for (variant, m_), agg in summary.items():
            if m_ != model:
                continue
            t = _welch_t(base_dlvls, agg["dlvls"]) if variant != baseline else None
            token_ratio = None
            base_tpt = summary.get((baseline, model), {}).get("mean_tokens_per_turn", 0)
            if base_tpt:
                token_ratio = agg["mean_tokens_per_turn"] / base_tpt
            rows.append((variant, agg, t, token_ratio))
        rows.sort(key=lambda r: r[1]["mean_max_dlvl"], reverse=True)
        lines.append("| variant | n (pending) | mean max-Dlvl | SEM | mean avg_score | Δ score vs B1 | t | tok/turn |")
        lines.append("|---|---|---|---|---|---|---|---|")
        base_score = summary.get((baseline, model), {}).get("mean_avg_score", 0) or 0
        for variant, agg, t, token_ratio in rows:
            delta = (agg.get("mean_avg_score", 0) or 0) - base_score if variant != baseline else 0.0
            t_str = f"{t:+.2f}" if t is not None else "—"
            pending = agg.get("n_pending", 0)
            n_str = f"{agg['n_seeds']}" + (f" ({pending} pending)" if pending else "")
            lines.append(
                f"| **{variant}** | {n_str} | "
                f"{agg['mean_max_dlvl']:.2f} | {agg['sem_max_dlvl']:.2f} | "
                f"{agg.get('mean_avg_score', 0):.3f} | {delta:+.3f} | {t_str} | "
                f"{agg['mean_tokens_per_turn']:.0f} |"
            )
        # Top-3 promotion list
        winners = [r for r in rows if r[0] != baseline][:3]
        if winners:
            lines.append("\n**Top-3 candidates to re-evaluate on secondary model:** "
                         + ", ".join(f"`{r[0]}`" for r in winners))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("paths", nargs="*", help="Two metadata.json paths (or omit for most-recent)")
    p.add_argument("--label-a", default=None)
    p.add_argument("--label-b", default=None)
    p.add_argument("--tag", default=None,
                   help="Aggregate by tag prefix (e.g. 'wave1') instead of pairwise compare. "
                        "Reads from experiments/results/<tag>/*/*/*/metadata.json and emits "
                        "experiments/results/<tag>_summary.md.")
    p.add_argument("--tag-base", default="experiments/results",
                   help="Base dir for tagged artifacts. Default: experiments/results")
    p.add_argument("--hosted", action="store_true",
                   help="With --tag, pull from `prime eval list` (hosted) instead of local artifact dir.")
    args = p.parse_args()

    # Tagged aggregation path: short-circuits pairwise compare.
    if args.tag:
        if args.hosted:
            summary = _aggregate_hosted(args.tag)
        else:
            base = Path(args.tag_base).resolve()
            summary = _aggregate_tag(args.tag, base)
        if not summary:
            src = "prime eval list" if args.hosted else f"{args.tag_base}/{args.tag}/"
            print(f"No artifacts found under {src}", file=sys.stderr)
            return 1
        out = Path(args.tag_base) / f"{args.tag}_summary.md"
        _emit_wave1_markdown(summary, out)
        print(f"wrote {out}")
        # Also print the summary to stdout for terminal viewers.
        print()
        print(out.read_text())
        return 0

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
