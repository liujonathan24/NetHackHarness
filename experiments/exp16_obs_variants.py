"""exp16: observation/skill-structure variant sweep.

Wave-1 baselines (all NetHack-origin or directly transferable per
docs/PROMPTING_SURVEY.md):

  B0  no-compaction calibration (raw v0.0.15-era obs, no RLE/strip/journal-diff)
  B1  current default compaction (the standing baseline)
  G   Glyphbox: ASCII + adjacency + hostile-list + code-mode tool
  B   BALROG / NLE language wrapper: NO ASCII map, natural-language obs only
  N   NetPlay: skill-only action surface (no `move(direction=…)` primitive)
  R   CPP/GPP summarize-and-reset: belief state every 25 turns,
      drop EVERYTHING before last belief checkpoint
  P   reserved for the variant produced by the subagent reviewing
      arxiv:2605.09998 (added dynamically if registered).

Each variant maps to a `load_environment(...)` kwarg set. The launcher
iterates the product (variant × model × seed) and either:

  --dry-run        : print the prime eval commands that would run
  --hosted         : queue on Prime Intellect's hosted infra
  --local          : run locally (serial; for smoke tests)

Defaults: seeds 22-41 (20 seeds), 200 max_turns, Qwen3.5-9B primary,
top-3 winners re-evaluated on Haiku in a follow-up.

Aggregation: after runs complete, `tools/compare_evals.py --tag wave1`
walks the resulting metadata.json files and emits
`experiments/results/wave1_summary.md`.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "experiments" / "results" / "wave1"

DEFAULT_SEEDS = list(range(22, 27))  # 5 seeds: 22..26 inclusive (primary stage)
SECONDARY_SEEDS = list(range(22, 25))  # 3 seeds: 22..24 (haiku promotion stage)
DEFAULT_MAX_TURNS = 200
PRIMARY_MODEL = "Qwen/Qwen3.5-9B"
SECONDARY_MODEL = "claude-haiku-4-5"


@dataclass
class Variant:
    name: str           # short code (B0, B1, G, B, N, R, P)
    description: str
    env_args: dict      # load_environment kwargs
    notes: str = ""


# Variant flags map to load_environment(...) kwargs. New flags introduced
# in environments/nethack/nethack.py:
#   - variant: str   — selects an observation/skill preset
#   - compact_obs: bool — already present
#   - skill_set: str — already present ('full', 'dir8', 'move', or csv)
# Other knobs (history_keep_full, belief_state_interval, etc.) are also
# already wired through load_environment.

VARIANTS: dict[str, Variant] = {
    "B0": Variant(
        name="B0",
        description="No-compaction calibration baseline (v0.0.15-era raw render)",
        env_args={
            "variant": "B1",          # canonical formatter, just with all token-savers OFF
            "compact_obs": False,
            "history_keep_full": 1000,    # effectively keep everything
            "history_drop_after": 100000,
            "belief_state_interval": 0,   # disable
            "journal_render_max_chars": 100000,
        },
        notes="Calibration only — establishes whether current compaction helps or hurts capability.",
    ),
    "B1": Variant(
        name="B1",
        description="Current default compaction (standing baseline)",
        env_args={
            "variant": "B1",
            "compact_obs": True,
            "history_keep_full": 5,
            "history_drop_after": 100,
            "belief_state_interval": 25,
            "journal_render_max_chars": 2000,
        },
        notes="The variant every other one must beat.",
    ),
    "G": Variant(
        name="G",
        description="Glyphbox: ASCII + adjacency + hostile list + code-mode tool",
        env_args={
            "variant": "G",
            "interface": "code",       # code-mode = Glyphbox's `execute_code` analog
            "compact_obs": True,
            "history_keep_full": 5,
            "history_drop_after": 100,
            "belief_state_interval": 25,
        },
        notes="Glyphbox blog (Ken Wang, Jan 2026). NetHack-origin.",
    ),
    "B": Variant(
        name="B",
        description="BALROG / NLE language wrapper: no ASCII grid",
        env_args={
            "variant": "B",
            "compact_obs": True,
            "history_keep_full": 5,
            "history_drop_after": 100,
            "belief_state_interval": 25,
        },
        notes="BALROG (Paglieri et al., ICLR 2025) text wrapper. NetHack-origin.",
    ),
    "N": Variant(
        name="N",
        description="NetPlay: skill-only action surface (no low-level move primitives)",
        env_args={
            "variant": "B1",          # formatter stays default
            "compact_obs": True,
            "history_keep_full": 5,
            "history_drop_after": 100,
            "belief_state_interval": 25,
            # The actual delta: a curated skill whitelist (no `move`).
            "skill_set": "move_to,autoexplore,find_and_descend,attack,descend,search,pickup,engrave_elbereth,pray,eat,quaff,read,add_note,recall,pin_objective,wiki_lookup,wiki_search,kick",
        },
        notes="NetPlay (Jeurissen, CoG 2024). NetHack-origin.",
    ),
    "R": Variant(
        name="R",
        description="CPP/GPP summarize-and-reset: drop everything before last belief checkpoint",
        env_args={
            "variant": "R",
            "compact_obs": True,
            "history_keep_full": 5,
            "history_drop_after": 25,    # collapses near the belief-state interval
            "belief_state_interval": 25,
            "summarize_and_reset": True, # NEW flag — env reads it to hard-drop pre-ckpt msgs
        },
        notes="Claude/Gemini Plays Pokemon. Survey rec #3 extended.",
    ),
    "P": Variant(
        name="P",
        description="Continual Harness (arXiv:2605.09998): mid-rollout self-refinement",
        env_args={
            "variant": "P",
            "refine_interval": 20,
            "compact_obs": True,
            "history_keep_full": 5,
            "history_drop_after": 100,
            "belief_state_interval": 25,
        },
        notes="Karten et al., 2026. Periodic self-refinement turn directives.",
    ),
}


def register_variant(v: Variant) -> None:
    """Lets the subagent (or any follow-up code) add 'P' without editing this file."""
    VARIANTS[v.name] = v


def _is_continual_supported() -> bool:
    """Forward-declared: continual harness mode is the second prong of this iteration."""
    try:
        from environments.nethack import nethack  # type: ignore
        return hasattr(nethack, "_CONTINUAL_SUPPORTED")
    except ImportError:
        return False


# ---------- run identification ----------


def run_tag(variant: str, model: str, seed: int) -> str:
    """Canonical run tag. Aggregator searches by `wave1/<variant>/<model>/seed<N>`."""
    safe_model = model.replace("/", "-")
    return f"wave1/{variant}/{safe_model}/seed{seed}"


def artifact_dir(variant: str, model: str, seed: int) -> Path:
    return RESULTS_DIR / variant / model.replace("/", "-") / f"seed{seed}"


# ---------- command construction ----------


def build_prime_eval_cmd(
    variant: Variant,
    model: str,
    seed: int,
    max_turns: int,
    hosted: bool,
) -> list[str]:
    """One `prime eval run` invocation for one (variant, model, seed)."""
    env_args = dict(variant.env_args)
    env_args["explicit_seeds"] = [seed]
    env_args["max_turns"] = max_turns
    env_args["n_examples"] = 1

    # `prime eval run` accepts --env-args as a JSON blob.
    env_args_json = json.dumps(env_args, separators=(",", ":"))
    tag = run_tag(variant.name, model, seed)
    out_dir = artifact_dir(variant.name, model, seed)

    cmd = [
        "prime", "eval", "run", "nethack",
        "--model", model,
        "--env-args", env_args_json,
        "-n", "1",
        "-r", "1",
        "--max-concurrent", "1",
    ]
    if hosted:
        # Hosted eval CLI rejects --output-dir/--save-results/--abbreviated-summary;
        # artifacts land on Prime infra and the aggregator pulls them by --eval-name.
        cmd += ["--hosted", "--eval-name", tag.replace("/", "-")]
    else:
        cmd += [
            "--save-results",
            "--output-dir", str(out_dir),
            "--abbreviated-summary",
        ]
    return cmd


# ---------- launcher ----------


def iter_jobs(
    variants: list[str],
    models: list[str],
    seeds: list[int],
    max_turns: int,
    hosted: bool,
    skip_existing: bool,
):
    for vname in variants:
        if vname not in VARIANTS:
            print(f"[warn] unknown variant {vname!r}; skipping", file=sys.stderr)
            continue
        v = VARIANTS[vname]
        for model in models:
            for seed in seeds:
                out_dir = artifact_dir(v.name, model, seed)
                if skip_existing and (out_dir / "metadata.json").exists():
                    yield ("skip", v, model, seed, None)
                    continue
                cmd = build_prime_eval_cmd(v, model, seed, max_turns, hosted)
                yield ("run", v, model, seed, cmd)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--variants", default="B0,B1,G,B,N,R",
                   help="Comma list. Default wave-1 slate.")
    p.add_argument("--models", default=PRIMARY_MODEL,
                   help=f"Comma list. Default {PRIMARY_MODEL} (primary). Promote top-3 to {SECONDARY_MODEL} after.")
    p.add_argument("--seeds", default=",".join(str(s) for s in DEFAULT_SEEDS),
                   help="Comma list of NLE seeds. Default 22-41.")
    p.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    p.add_argument("--hosted", action="store_true", help="Queue on Prime Intellect hosted infra.")
    p.add_argument("--dry-run", action="store_true", help="Print commands; do not execute.")
    p.add_argument("--skip-existing", action="store_true", default=True,
                   help="Skip jobs whose artifact_dir already has metadata.json.")
    p.add_argument("--no-skip-existing", dest="skip_existing", action="store_false")
    args = p.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]

    total = len(variants) * len(models) * len(seeds)
    print(f"# wave-1 sweep: {len(variants)} variants x {len(models)} models x {len(seeds)} seeds = {total} jobs",
          file=sys.stderr)

    queued = skipped = failed = 0
    for status, v, model, seed, cmd in iter_jobs(
        variants, models, seeds, args.max_turns, args.hosted, args.skip_existing,
    ):
        if status == "skip":
            skipped += 1
            print(f"[skip] {v.name} {model} seed={seed} (artifact present)", file=sys.stderr)
            continue
        line = " ".join(shlex.quote(c) for c in cmd)
        if args.dry_run:
            print(line)
            queued += 1
            continue
        print(f"[launch] {v.name} {model} seed={seed}", file=sys.stderr)
        rc = subprocess.call(cmd)
        if rc == 0:
            queued += 1
        else:
            failed += 1
            print(f"[fail] {v.name} {model} seed={seed} rc={rc}", file=sys.stderr)

    print(f"# done: queued={queued} skipped={skipped} failed={failed}", file=sys.stderr)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
