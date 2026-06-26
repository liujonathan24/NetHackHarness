"""Harness-iteration loop orchestrator + CLI.

Run:  python -m approaches.continuous_harness.loop --iterations N [...flags]

Each iteration:
  1. create a fresh git worktree (isolation + reproducibility)
  2. symlink the immutable engine + the shared .venv into it
  3. write the bootstrap_dir (seed<N>.json) from the current HarnessConfig
  4. run the CH eval inside the worktree (or, in --dry-run, synthesize a
     deterministic fake depth — NO API, NO budget)
  5. parse depth from the trace NDJSON, record it, update the leaderboard
  6. propose the next config from the last result
  7. remove the iteration worktree (unless --keep-worktrees)

INVARIANT: the loop only ever changes env-args + the bootstrap files. It NEVER
modifies third_party/NetHack/** (the game engine) or nethack_core/**. A guard
(`assert_engine_untouched`) fails the iteration if those paths would be written.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from .config import HarnessConfig
from .proposer import FallbackProposer, LLMProposer, Proposer

# Engine paths that must NEVER be mutated by the loop (relative to a worktree root).
_IMMUTABLE_PATHS = ("third_party/NetHack", "third_party/nethack", "nethack_core")


# ---------------------------------------------------------------------------- #
# immutable-game guard
# ---------------------------------------------------------------------------- #
def assert_engine_untouched(worktree: Path) -> None:
    """Fail loudly if the iteration would mutate engine source.

    Two checks:
      1. The engine dir must be a SYMLINK (a shared pointer back to the source
         tree), never a real copy the iteration could edit in place.
      2. `git status --porcelain` inside the worktree must report no changes
         under any immutable path.
    """
    root = worktree.resolve()
    # 1. engine dir must be a symlink (or absent — submodule not materialized).
    engine = root / "third_party" / "NetHack"
    if engine.exists() and not engine.is_symlink():
        raise RuntimeError(
            f"IMMUTABLE-GAME GUARD: {engine} is a real directory, not a symlink. "
            "The loop must symlink the engine, never copy it, so it cannot be "
            "patched per-iteration."
        )
    # 2. no staged/unstaged changes under any immutable path.
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--", *_IMMUTABLE_PATHS],
            capture_output=True, text=True, check=False,
        ).stdout
    except Exception:
        out = ""
    dirty = [ln for ln in out.splitlines() if ln.strip()]
    if dirty:
        raise RuntimeError(
            "IMMUTABLE-GAME GUARD: detected changes under engine paths "
            f"{_IMMUTABLE_PATHS}:\n" + "\n".join(dirty)
        )


# ---------------------------------------------------------------------------- #
# worktree mechanics
# ---------------------------------------------------------------------------- #
def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, check=False,
    )


def make_iteration_worktree(
    current: Path, iter_dir: Path, branch: str
) -> None:
    """Create the iteration worktree off HEAD, then wire in the shared engine
    symlink and the shared .venv symlink (matching how this worktree was set up).
    """
    iter_dir.parent.mkdir(parents=True, exist_ok=True)
    res = _git(current, "worktree", "add", str(iter_dir), "-b", branch, "HEAD")
    if res.returncode != 0:
        raise RuntimeError(f"git worktree add failed:\n{res.stdout}\n{res.stderr}")

    # Engine: a fresh worktree has an empty submodule dir. Remove it and symlink
    # the immutable engine from the current worktree (which itself points at the
    # source tree). NEVER copy.
    src_engine = (current / "third_party" / "NetHack").resolve()
    dst_engine = iter_dir / "third_party" / "NetHack"
    dst_engine.parent.mkdir(parents=True, exist_ok=True)
    if dst_engine.exists() or dst_engine.is_symlink():
        if dst_engine.is_symlink() or dst_engine.is_file():
            dst_engine.unlink()
        else:
            shutil.rmtree(dst_engine)
    if src_engine.exists():
        os.symlink(src_engine, dst_engine)

    # venv: reuse the current worktree's .venv (MVP only mutates env-ARGS, not
    # env code, so the installed `nethack` package is identical).
    src_venv = (current / ".venv").resolve()
    dst_venv = iter_dir / ".venv"
    if dst_venv.exists() or dst_venv.is_symlink():
        if dst_venv.is_symlink():
            dst_venv.unlink()
    if src_venv.exists() and not dst_venv.exists():
        os.symlink(src_venv, dst_venv)


def remove_iteration_worktree(current: Path, iter_dir: Path, branch: str) -> None:
    _git(current, "worktree", "remove", "--force", str(iter_dir))
    # Best-effort branch cleanup.
    _git(current, "branch", "-D", branch)
    # If the dir somehow survived, nuke it.
    if iter_dir.exists():
        shutil.rmtree(iter_dir, ignore_errors=True)


# ---------------------------------------------------------------------------- #
# bootstrap writing
# ---------------------------------------------------------------------------- #
def write_bootstrap(bootstrap_dir: Path, cfg: HarnessConfig) -> Path:
    """Write seed<N>.json (snapshot_components shape) for the configured seed
    range into bootstrap_dir. Returns the dir path."""
    bootstrap_dir.mkdir(parents=True, exist_ok=True)
    # Write one file per seed the eval will touch (seed .. seed+n_seeds-1), since
    # the env loads seed<seed>.json keyed on the per-rollout seed.
    for s in range(cfg.seed, cfg.seed + max(1, cfg.n_seeds)):
        (bootstrap_dir / f"seed{s}.json").write_text(cfg.to_bootstrap_json(s))
    return bootstrap_dir


# ---------------------------------------------------------------------------- #
# depth parsing
# ---------------------------------------------------------------------------- #
def _depth_from_ndjson(path: Path) -> Optional[int]:
    """Per-rollout score = the best curriculum progress over its turns.

    Prefers `curriculum_floor` (1..6, the seed-robust curriculum axis: floor 6
    is the seed's clamped deep bottom). Curriculum floor is the right metric
    because absolute depth DROPS on the ascent and jumps discontinuously across
    the DoD3->Gehennom boundary. Falls back to `max_dlvl_reached`, then `dlvl`,
    for non-curriculum tiers."""
    best_floor = None
    best_max = None
    best_dlvl = None
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            for fk in ("max_curriculum_floor", "curriculum_floor"):
                fv = rec.get(fk)
                if isinstance(fv, int):
                    best_floor = fv if best_floor is None else max(best_floor, fv)
            v = rec.get("max_dlvl_reached")
            if isinstance(v, int):
                best_max = v if best_max is None else max(best_max, v)
            d = rec.get("dlvl")
            if isinstance(d, int):
                best_dlvl = d if best_dlvl is None else max(best_dlvl, d)
    except Exception:
        return None
    if best_floor is not None:
        return best_floor
    if best_max is not None:
        return best_max
    return best_dlvl


def parse_iteration_depth(trace_dir: Path) -> tuple[float, list[int]]:
    """Mean per-rollout depth over all NDJSON trace files under trace_dir.
    Returns (mean_depth, per_rollout_depths)."""
    depths: list[int] = []
    if trace_dir.exists():
        for f in sorted(trace_dir.glob("*.ndjson")):
            d = _depth_from_ndjson(f)
            if d is not None:
                depths.append(d)
    mean = (sum(depths) / len(depths)) if depths else 0.0
    return mean, depths


def parse_mean_reward(results_root: Path) -> Optional[float]:
    """Best-effort: pull a mean reward from vf-eval's saved results metadata.
    vf-eval writes under <cwd>/outputs/evals/.../metadata.json; we scan for the
    newest metadata.json and look for a reward-ish mean. Returns None if absent."""
    try:
        candidates = sorted(
            results_root.rglob("metadata.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except Exception:
        return None
    for meta in candidates[:5]:
        try:
            data = json.loads(meta.read_text())
        except Exception:
            continue
        for key in ("reward", "mean_reward", "avg_reward"):
            v = data.get(key)
            if isinstance(v, (int, float)):
                return float(v)
        # nested {"metrics": {"reward": {"mean": ...}}}
        metrics = data.get("metrics")
        if isinstance(metrics, dict):
            r = metrics.get("reward")
            if isinstance(r, dict) and isinstance(r.get("mean"), (int, float)):
                return float(r["mean"])
    return None


# ---------------------------------------------------------------------------- #
# eval execution
# ---------------------------------------------------------------------------- #
def run_eval(
    iter_dir: Path,
    cfg: HarnessConfig,
    bootstrap_dir: Path,
    trace_dir: Path,
    *,
    env_sh: str,
    dry_run: bool,
) -> dict[str, Any]:
    """Run the CH eval inside the iteration worktree. In --dry-run, skip the real
    eval entirely and return a deterministic synthetic depth (NO API)."""
    if dry_run:
        return _synthesize_dry_run(cfg, trace_dir)

    env_args = cfg.to_env_args(str(bootstrap_dir), str(trace_dir))
    # Use the iteration worktree's OWN code, not the venv's installed copy. The
    # `nethack` module is installed as a stale site-packages file and
    # `nethack_harness`/`nethack_core` are editable-installed pointing at the
    # MAIN repo checkout — so without an explicit PYTHONPATH the eval would run
    # the main repo's harness, NOT this iteration's committed edits. Prepending
    # the iter worktree's env dir + root makes the iteration's source win over
    # both the stale file and the main-repo editable. (Documented gotcha.)
    pythonpath = f"{iter_dir}/environments/nethack:{iter_dir}"
    # Drive vf-eval through the symlinked venv binary directly. `uv run` would
    # try to re-sync the iteration worktree's project (whose lockfile references
    # a gitignored workspace member) and fail; the venv already has everything.
    venv_vf = str(iter_dir / ".venv" / "bin" / "vf-eval")
    eval_cmd = [
        venv_vf, "nethack",
        "--provider", "prime",
        "-m", cfg.policy_model,
        "-n", str(cfg.n_seeds),
        "-r", "1",
        "-a", json.dumps(env_args),
        "--disable-tui",
        "--save-results",
    ]
    # `source` requires a shell; wrap in bash -lc. Source the teacher creds
    # (PI_API_KEY / REFINER_API_KEY / REFINER_BASE_URL) and prepend PYTHONPATH.
    shell_cmd = (
        f"source {shlex_quote(env_sh)} && "
        f"export PYTHONPATH={shlex_quote(pythonpath)}:$PYTHONPATH && "
        + " ".join(shlex_quote(c) for c in eval_cmd)
    )
    proc = subprocess.run(
        ["bash", "-lc", shell_cmd],
        cwd=str(iter_dir),
        capture_output=True, text=True, check=False,
    )
    return {
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
    }


def shlex_quote(s: str) -> str:
    import shlex
    return shlex.quote(s)


def _synthesize_dry_run(cfg: HarnessConfig, trace_dir: Path) -> dict[str, Any]:
    """Write deterministic fake NDJSON trace files so the rest of the pipeline
    (depth parsing, leaderboard, run-log) exercises real code paths with NO API
    call and NO budget. Depth is a stable function of (variant, skill_set,
    addendum) so the leaderboard is reproducible across runs."""
    trace_dir.mkdir(parents=True, exist_ok=True)
    base = 1
    base += (hash(cfg.variant) % 5)
    base += 1 if cfg.prompt_addendum else 0
    base += 1 if cfg.skill_set != "full" else 0
    for s in range(cfg.seed, cfg.seed + max(1, cfg.n_seeds)):
        depth = max(1, base + (s % 2))
        recs = []
        for t in range(3):
            recs.append(json.dumps({
                "turn": t,
                "variant": cfg.variant,
                "dlvl": min(t + 1, depth),
                "max_dlvl_reached": min(t + 1, depth),
                "hp": 16,
            }))
        (trace_dir / f"dryrun_seed{s}.ndjson").write_text("\n".join(recs) + "\n")
    return {"returncode": 0, "stdout_tail": "[dry-run: synthesized trace]",
            "stderr_tail": "", "dry_run": True}


# ---------------------------------------------------------------------------- #
# orchestrator
# ---------------------------------------------------------------------------- #
def run_loop(args: argparse.Namespace) -> dict[str, Any]:
    current = Path.cwd().resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    runid = time.strftime("%Y%m%d-%H%M%S")

    base_cfg = HarnessConfig(
        variant="CH" if not args.dry_run else "B1",
        skill_set=args.skill_set,
        prompt_addendum=None,
        tier=args.tier,
        policy_model=args.policy,
        teacher_model=args.teacher,
        max_turns=args.max_turns,
        refine_interval=args.refine_interval,
        seed=args.seed,
        n_seeds=args.n_seeds,
    ).validate()

    proposer: Proposer
    if args.proposer == "llm" and not args.dry_run:
        proposer = LLMProposer(model=args.teacher)
    else:
        proposer = FallbackProposer()

    history: list[dict[str, Any]] = []
    iteration_records: list[dict[str, Any]] = []

    cfg = base_cfg
    for i in range(args.iterations):
        iter_branch = f"harness-iter-{runid}-{i}"
        iter_dir = current / ".claude" / "worktrees" / "harness-iter" / f"iter{i}"
        trace_dir = out_dir / f"iter{i}" / "trace"
        bootstrap_dir = out_dir / f"iter{i}" / "bootstrap"
        results_root = iter_dir / "outputs"

        print(f"\n=== Iteration {i} ===")
        print(f"config: {json.dumps(cfg.summary())}")

        eval_result: dict[str, Any] = {}
        guard_ok = True
        guard_err = None
        try:
            make_iteration_worktree(current, iter_dir, iter_branch)
            write_bootstrap(bootstrap_dir, cfg)
            # IMMUTABLE-GAME GUARD: after wiring, before/after eval, the engine
            # must remain untouched.
            assert_engine_untouched(iter_dir)
            eval_result = run_eval(
                iter_dir, cfg, bootstrap_dir, trace_dir,
                env_sh=args.env_sh, dry_run=args.dry_run,
            )
            assert_engine_untouched(iter_dir)
        except Exception as e:  # noqa: BLE001
            guard_ok = False
            guard_err = str(e)
            print(f"[iteration {i}] ERROR: {e}", file=sys.stderr)
        finally:
            if not args.keep_worktrees and iter_dir.exists():
                remove_iteration_worktree(current, iter_dir, iter_branch)

        mean_depth, per_rollout = parse_iteration_depth(trace_dir)
        mean_reward = None
        if not args.dry_run:
            mean_reward = parse_mean_reward(results_root if results_root.exists()
                                            else out_dir)

        rec = {
            "iteration": i,
            "branch": iter_branch,
            "config": cfg.summary(),
            "mean_depth": mean_depth,
            "per_rollout_depths": per_rollout,
            "mean_reward": mean_reward,
            "guard_ok": guard_ok,
            "guard_error": guard_err,
            "eval": {k: v for k, v in eval_result.items()
                     if k != "stdout_tail" or args.verbose},
            "trace_dir": str(trace_dir),
            "bootstrap_dir": str(bootstrap_dir),
        }
        iteration_records.append(rec)
        print(f"iteration {i}: mean_depth={mean_depth:.2f} "
              f"depths={per_rollout} reward={mean_reward}")

        # Build the compact history entry for the proposer.
        excerpt = _trajectory_excerpt(trace_dir)
        history.append({
            "config": cfg.summary(),
            "depth": mean_depth,
            "reward": mean_reward,
            "excerpt": excerpt,
        })

        # Propose the next config (skip on the last iteration).
        if i < args.iterations - 1:
            cfg = proposer.propose(base_cfg, history)

    # Leaderboard: best config by mean_depth.
    leaderboard = sorted(
        iteration_records, key=lambda r: r["mean_depth"], reverse=True
    )
    _print_leaderboard(leaderboard)

    run_log = {
        "runid": runid,
        "dry_run": args.dry_run,
        "proposer": args.proposer if not args.dry_run else "fallback",
        "iterations": args.iterations,
        "base_config": base_cfg.summary(),
        "records": iteration_records,
        "leaderboard": [
            {"iteration": r["iteration"], "mean_depth": r["mean_depth"],
             "config": r["config"]}
            for r in leaderboard
        ],
        "best": leaderboard[0] if leaderboard else None,
    }
    run_log_path = out_dir / f"run_log_{runid}.json"
    run_log_path.write_text(json.dumps(run_log, indent=2))
    print(f"\nrun-log written: {run_log_path}")
    return run_log


def _trajectory_excerpt(trace_dir: Path, max_chars: int = 600) -> str:
    """Grab a short excerpt of the last rollout's final turns for proposer context."""
    files = sorted(trace_dir.glob("*.ndjson")) if trace_dir.exists() else []
    if not files:
        return ""
    try:
        lines = files[-1].read_text().splitlines()
    except Exception:
        return ""
    tail = lines[-3:]
    return "\n".join(tail)[:max_chars]


def _print_leaderboard(leaderboard: list[dict[str, Any]]) -> None:
    print("\n================ LEADERBOARD (by mean depth) ================")
    print(f"{'rank':<5}{'iter':<6}{'depth':<8}{'variant':<8}{'skill_set':<12}addendum")
    for rank, r in enumerate(leaderboard):
        c = r["config"]
        add = "yes" if c.get("prompt_addendum") else "no"
        print(f"{rank:<5}{r['iteration']:<6}{r['mean_depth']:<8.2f}"
              f"{c.get('variant',''):<8}{str(c.get('skill_set','')):<12}{add}")
    if leaderboard:
        best = leaderboard[0]
        print(f"\nBEST: iteration {best['iteration']} "
              f"depth={best['mean_depth']:.2f} config={json.dumps(best['config'])}")
    print("============================================================")


# ---------------------------------------------------------------------------- #
# CLI
# ---------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m approaches.continuous_harness.loop",
        description="Self-improving harness-iteration loop for the NetHack env. "
                    "Mutates only obs-format / tools / prompt; the game engine "
                    "is immutable.",
    )
    p.add_argument("--iterations", type=int, default=3)
    p.add_argument("--policy", default="z-ai/glm-4.6", help="policy model id")
    p.add_argument("--teacher", default="z-ai/glm-5",
                   help="teacher/refiner + LLM-proposer model id (must differ "
                        "from --policy)")
    p.add_argument("--tier", default="corridor_explore")
    p.add_argument("--skill-set", dest="skill_set", default="full",
                   help="base tool surface: 'full'/'move'/'dir8'/'netplay' or a "
                        "comma-allowlist (e.g. the primitives-curriculum set "
                        "'move,move_to,autoexplore,search,press_down,press_up,...'). "
                        "The LLM proposer may further mutate it between iters.")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--n-seeds", dest="n_seeds", type=int, default=1)
    p.add_argument("--max-turns", dest="max_turns", type=int, default=200)
    p.add_argument("--refine-interval", dest="refine_interval", type=int, default=20)
    p.add_argument("--proposer", choices=("llm", "fallback"), default="fallback")
    p.add_argument("--dry-run", action="store_true",
                   help="skip the real eval; synthesize deterministic depth. "
                        "NO API, NO budget. Forces the fallback proposer.")
    p.add_argument("--keep-worktrees", action="store_true",
                   help="do not git-worktree-remove iteration worktrees after "
                        "parsing results (default: auto-remove).")
    p.add_argument("--out", default="/tmp/harness_loop_run",
                   help="output dir for traces, bootstraps, and the run-log.")
    p.add_argument("--env-sh", dest="env_sh", default="/tmp/ch_env.sh",
                   help="shell file that exports PI_API_KEY / REFINER_API_KEY / "
                        "REFINER_BASE_URL (sourced before vf-eval).")
    p.add_argument("--verbose", action="store_true")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.policy == args.teacher:
        print("ERROR: --policy and --teacher must differ (Prime Inference serves "
              "both).", file=sys.stderr)
        return 2
    run_loop(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
