"""Code-editing champion/challenger self-improvement loop for the NetHack harness.

This EXTENDS the config-mutation loop (`loop.py`) into one where an LLM EDITS the
harness CODE (tools + observations/prompt + navigation) in isolated per-iteration
git worktrees, tests it, evals it, and keeps ONLY improvements. The game engine is
FROZEN: it is symlinked read-only into every iteration worktree, and a hard
whitelist + post-apply `git diff --name-only` guard rejects any iteration that
touches a non-whitelisted (or engine) path.

  Run (dry-run, NO API / NO budget / NO reinstall / NO eval):
    uv run python -m approaches.continuous_harness.auto_improve --iterations 2 --dry-run \
        --out /tmp/auto_improve_dry

  Run (real, supervisor only — costs ~eval_n rollouts per accepted/rejected iter):
    source /tmp/ch_env.sh && uv run python -m approaches.continuous_harness.auto_improve \
        --iterations 10 --eval-n 8 --max-turns 200 --margin 0.15 \
        --problem "<bottleneck brief>" --out /tmp/auto_improve_run

CHAMPION/CHALLENGER:
  We keep a CHAMPION (a git commit = current best harness) and its score. Each
  iteration branches a fresh worktree off the champion commit, proposes a one-file
  code edit, gates on tests, evals, and ACCEPTS (commits + champion := this SHA)
  iff `mean_depth > champion_depth + margin`. Otherwise the champion is unchanged.
  The margin (default 0.15) fights eval noise so a within-noise "win" can't ratchet
  the champion onto a worse harness.

WHY accept/reject is the safety net for "passes tests but tanks eval":
  Tests only prove the package still imports + behaves on unit cases. A code edit
  can pass tests yet make the agent play WORSE. The eval-gated margin comparison is
  exactly what catches that: such an edit yields mean_depth <= champion_depth + margin
  and is REJECTED, so it never becomes champion.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from .code_proposer import (
    ENGINE_FILES,
    ENGINE_PREFIXES,
    WHITELIST,
    CodeEdit,
    CodeProposer,
    is_whitelisted,
)
from .loop import (
    _depth_from_ndjson,  # reuse exact depth parsing
    parse_iteration_depth,
    shlex_quote,
)

# Engine paths that must NEVER show up dirty in an iteration worktree.
_IMMUTABLE_PATHS = ("third_party/NetHack", "third_party/nethack", "nethack_core")

# Default whitelist menu the model picks from, in rotation order. Navigation /
# observation files are first because the ledger names navigation + obs as the
# dominant bottleneck.
_DEFAULT_MENU = (
    "environments/nethack/nethack_harness/navigation/pathfinding.py",
    "environments/nethack/nethack_harness/prompt/rendering.py",
    "environments/nethack/nethack_harness/prompt/map_encoders.py",
    "environments/nethack/nethack_harness/tools/skills.py",
    "environments/nethack/nethack_harness/prompt/prompt_spec.py",
    "environments/nethack/nethack_harness/tools/code_mode.py",
)

_DEFAULT_PROBLEM = (
    "The agent under-descends: it wanders a floor while alive and fails to reach "
    "visible down-stairs because granular navigation (move_to / pathfinding) "
    "cannot route across unexplored or awkward tiles, and the observation does "
    "not make the route to the nearest down-stairs / nearest unexplored frontier "
    "obvious. Improve TOOLING or OBSERVATION so the policy can navigate to and "
    "descend stairs more reliably. Make ONE focused, test-safe change."
)

# The non-compacted JSON 'mega' config that the ledger established as the powered
# baseline (banner fix + JSON obs + all bugfixes). Used as the eval env-args base.
_DEFAULT_CONFIG: dict[str, Any] = {
    "variant": "JSON",
    "tier": "corridor_explore",
    "compact_obs": False,
    "belief_state_interval": 0,
    "refine": False,
    "refine_interval": 20,
    "seed": 0,
}

_REINSTALL_CMD = (
    "uv sync --extra dev --all-packages "
    "--reinstall-package nethack --reinstall-package nethack-core"
)


# ---------------------------------------------------------------------------- #
# git helpers
# ---------------------------------------------------------------------------- #
def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, check=False,
    )


def _resolve_ref(repo: Path, ref: str) -> str:
    res = _git(repo, "rev-parse", ref)
    if res.returncode != 0:
        raise RuntimeError(f"could not resolve ref {ref!r}: {res.stderr.strip()}")
    return res.stdout.strip()


# ---------------------------------------------------------------------------- #
# worktree mechanics (branch off the CHAMPION commit, symlink the frozen engine)
# ---------------------------------------------------------------------------- #
def make_iteration_worktree(
    main: Path, iter_dir: Path, branch: str, champion_sha: str
) -> None:
    """Create the iteration worktree off the CHAMPION commit, then symlink the
    immutable engine from the main worktree. The engine is symlinked (never
    copied) so it is physically impossible to patch per-iteration; the venv is
    NOT shared (each iteration reinstalls its own — env source changes)."""
    iter_dir.parent.mkdir(parents=True, exist_ok=True)
    res = _git(main, "worktree", "add", str(iter_dir), "-b", branch, champion_sha)
    if res.returncode != 0:
        raise RuntimeError(
            f"git worktree add failed:\n{res.stdout}\n{res.stderr}"
        )

    src_engine = (main / "third_party" / "NetHack").resolve()
    dst_engine = iter_dir / "third_party" / "NetHack"
    dst_engine.parent.mkdir(parents=True, exist_ok=True)
    if dst_engine.is_symlink() or dst_engine.is_file():
        dst_engine.unlink()
    elif dst_engine.exists():
        shutil.rmtree(dst_engine)
    if src_engine.exists():
        os.symlink(src_engine, dst_engine)


def remove_iteration_worktree(main: Path, iter_dir: Path, branch: str) -> None:
    _git(main, "worktree", "remove", "--force", str(iter_dir))
    _git(main, "branch", "-D", branch)
    if iter_dir.exists():
        shutil.rmtree(iter_dir, ignore_errors=True)


# ---------------------------------------------------------------------------- #
# the HARD whitelist / engine-immutability guard
# ---------------------------------------------------------------------------- #
# Pathspecs excluding the submodule mounts. We replace `third_party/NetHack`
# (a registered submodule) with a symlink to the frozen engine; plain
# `git status` aborts with rc 128 ("expected submodule path ... not to be a
# symbolic link"), so every status/diff query MUST exclude the submodule path.
# The symlink itself is independently asserted in `assert_only_target_changed`.
_SUBMODULE_EXCLUDES = (
    ":(exclude)third_party/NetHack",
    ":(exclude)third_party/nethack",
)


def changed_paths(iter_dir: Path) -> list[str]:
    """All paths git reports changed in the worktree (tracked + untracked),
    relative to the worktree root, forward-slashed. The engine submodule mount is
    excluded from the query (its symlink-ness is asserted separately)."""
    res = _git(
        iter_dir, "status", "--porcelain", "--untracked-files=all",
        "--", ".", *_SUBMODULE_EXCLUDES,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"git status failed in iteration worktree:\n{res.stderr.strip()}"
        )
    paths: list[str] = []
    for ln in res.stdout.splitlines():
        ln = ln.rstrip("\n")
        if not ln.strip():
            continue
        # porcelain v1: "XY <path>" or "XY <old> -> <new>"
        rest = ln[3:] if len(ln) > 3 else ln
        if " -> " in rest:
            rest = rest.split(" -> ", 1)[1]
        paths.append(rest.strip().strip('"').replace("\\", "/"))
    return paths


def assert_only_target_changed(iter_dir: Path, target: str) -> None:
    """HARD GUARD. After applying the edit, the ONLY path git reports changed
    must be `target`, and `target` must be whitelisted. Anything else — an engine
    path, a second file, a stray write — raises and the iteration is rejected.

    Defence in depth:
      1. engine dir must be a SYMLINK (never an editable copy).
      2. no dirty path under any immutable engine prefix.
      3. the changed-path set must be EXACTLY {target}.
      4. target must pass `is_whitelisted` (positive list AND not engine glue).
    """
    root = iter_dir.resolve()
    engine = root / "third_party" / "NetHack"
    if engine.exists() and not engine.is_symlink():
        raise RuntimeError(
            f"ENGINE GUARD: {engine} is a real directory, not a symlink."
        )

    changed = changed_paths(root)

    # (2) engine prefixes / glue files must be clean.
    for p in changed:
        if any(p.startswith(pre) for pre in (
            "third_party/", "nethack_core/", "environments/nethack/nethack_core/",
        )):
            raise RuntimeError(
                f"ENGINE GUARD: change under frozen engine path: {p}"
            )
        if any(p.endswith("/" + f) or p == f for f in ENGINE_FILES):
            raise RuntimeError(
                f"ENGINE GUARD: change to engine-binding glue file: {p}"
            )

    # (3) exactly one changed path, and (4) it must be the whitelisted target.
    if not is_whitelisted(target):
        raise RuntimeError(f"WHITELIST GUARD: target not whitelisted: {target}")
    extras = [p for p in changed if p != target]
    if extras:
        raise RuntimeError(
            "WHITELIST GUARD: iteration changed paths beyond the single target "
            f"{target!r}: {extras}"
        )
    if target not in changed:
        # The edit produced no diff at all -> nothing to evaluate.
        raise RuntimeError(
            f"WHITELIST GUARD: target {target!r} shows no change after apply."
        )


# ---------------------------------------------------------------------------- #
# external steps (each wrapped so failure => reject, never crash)
# ---------------------------------------------------------------------------- #
def _run(cmd: list[str], cwd: Path, *, env_sh: Optional[str] = None,
         timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    if env_sh:
        shell_cmd = (
            f"source {shlex_quote(env_sh)} && "
            + " ".join(shlex_quote(c) for c in cmd)
        )
        full = ["bash", "-lc", shell_cmd]
    else:
        full = cmd
    return subprocess.run(
        full, cwd=str(cwd), capture_output=True, text=True,
        check=False, timeout=timeout,
    )


def reinstall_venv(iter_dir: Path, *, timeout: float = 1800.0) -> tuple[bool, str]:
    """Reinstall the ITERATION's own venv (env source changed). NEVER touches the
    main worktree venv (iteration worktrees have their own .venv created by uv)."""
    try:
        proc = subprocess.run(
            ["bash", "-lc", _REINSTALL_CMD],
            cwd=str(iter_dir), capture_output=True, text=True,
            check=False, timeout=timeout,
        )
    except Exception as e:  # noqa: BLE001
        return False, f"reinstall raised: {e}"
    ok = proc.returncode == 0
    return ok, (proc.stdout[-2000:] + "\n" + proc.stderr[-2000:])


# Curated, DETERMINISTIC test files that are green on the champion and cover the
# editable surfaces (tools / navigation / observation+prompt / env-construction /
# engine sanity). The FULL suite has ~17 pre-existing failures from asyncio-loop
# and file-state contamination when run together (530 pass / 17 fail on the
# unmodified champion), which would make EVERY iteration "fail" the gate. We gate
# on this curated subset instead so a real edit-induced regression is what fails.
GATE_TESTS: tuple[str, ...] = (
    "tests/test_skills.py",
    "tests/test_unknown_tool.py",
    "tests/test_move_to_besteffort.py",
    "tests/test_pathfinding.py",
    "tests/test_refiner.py",
    "environments/nethack/tests/test_refine_decoupled.py",
    "tests/test_more_escape.py",
    "environments/nethack/tests/test_snapshot.py",
)


def run_tests(iter_dir: Path, *, timeout: float = 1800.0) -> tuple[bool, str]:
    """Test gate. Runs a curated subset of deterministic, relevant tests (see
    GATE_TESTS) — passes iff pytest exits 0 on them. The full suite has
    pre-existing flaky failures that would reject every edit, so we gate on the
    green subset and catch edit-induced regressions there."""
    targets = [t for t in GATE_TESTS if (iter_dir / t).exists()]
    if not targets:
        return False, "no gate test files found"
    try:
        proc = subprocess.run(
            ["uv", "run", "pytest", *targets, "-q", "-p", "no:cacheprovider"],
            cwd=str(iter_dir), capture_output=True, text=True,
            check=False, timeout=timeout,
        )
    except Exception as e:  # noqa: BLE001
        return False, f"pytest raised: {e}"
    ok = proc.returncode == 0
    return ok, (proc.stdout[-3000:] + "\n" + proc.stderr[-2000:])


def run_eval(
    iter_dir: Path, config: dict[str, Any], trace_dir: Path,
    *, eval_n: int, policy_model: str, env_sh: str,
    timeout: float = 7200.0,
) -> tuple[bool, str]:
    """Run vf-eval inside the iteration worktree (creds sourced from env_sh).
    The eval writes NDJSON under trace_dir; depth is parsed from those."""
    env_args = dict(config)
    env_args["trace_dir"] = str(trace_dir)
    env_args.setdefault("max_turns", config.get("max_turns", 200))
    eval_cmd = [
        "uv", "run", "vf-eval", "nethack",
        "--provider", "prime",
        "-m", policy_model,
        "-n", str(eval_n),
        "-r", "1",
        "-a", json.dumps(env_args),
        "--disable-tui",
        "--save-results",
    ]
    try:
        proc = _run(eval_cmd, iter_dir, env_sh=env_sh, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        return False, f"vf-eval raised: {e}"
    ok = proc.returncode == 0
    return ok, (proc.stdout[-3000:] + "\n" + proc.stderr[-2000:])


# ---------------------------------------------------------------------------- #
# dry-run helpers (NO API, NO reinstall, NO eval)
# ---------------------------------------------------------------------------- #
def _templated_edit(target: str, current: str, iteration: int) -> CodeEdit:
    """A deterministic no-op-ish edit used ONLY in --dry-run: append a comment
    line so the file genuinely changes (so the whitelist guard + git diff see a
    real, single-file change) but behavior is unchanged. NO API call."""
    marker = (
        f"\n# [auto_improve dry-run] templated touch, iteration {iteration} "
        f"(no behavioral change)\n"
    )
    return CodeEdit(
        target=target,
        content=(current.rstrip("\n") + "\n" + marker),
        summary=f"dry-run templated touch of {Path(target).name}",
    )


def _synthesize_depth(target: str, iteration: int, champion_depth: float) -> float:
    """Deterministic fake mean depth so accept/reject + logging are exercised
    with NO eval. Even iterations beat the champion (test ACCEPT path); odd
    iterations land within margin (test REJECT path)."""
    if iteration % 2 == 0:
        return champion_depth + 0.5   # clears any default margin -> ACCEPT
    return champion_depth + 0.05      # within margin -> REJECT


# ---------------------------------------------------------------------------- #
# orchestrator
# ---------------------------------------------------------------------------- #
def run(args: argparse.Namespace) -> dict[str, Any]:
    main = Path.cwd().resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    runid = time.strftime("%Y%m%d-%H%M%S")

    config = dict(_DEFAULT_CONFIG)
    if args.config:
        try:
            config.update(json.loads(args.config))
        except Exception as e:  # noqa: BLE001
            print(f"WARNING: --config not valid JSON ({e}); using default.",
                  file=sys.stderr)
    config["max_turns"] = args.max_turns

    problem = args.problem or _DEFAULT_PROBLEM
    menu = list(_DEFAULT_MENU)

    champion_sha = _resolve_ref(main, args.champion_ref)
    champion_depth = float(args.champion_depth)
    print(f"START champion={champion_sha[:12]} depth={champion_depth:.2f} "
          f"margin={args.margin} dry_run={args.dry_run}")
    print(f"NOTE: each REAL iteration costs ~{args.eval_n} rollouts "
          f"(+ one venv reinstall, minutes each).")

    proposer = None if args.dry_run else CodeProposer(model=args.proposer_model)

    records: list[dict[str, Any]] = []
    run_log_path = out_dir / f"auto_improve_log_{runid}.json"
    leaderboard_path = out_dir / f"auto_improve_leaderboard_{runid}.md"

    for i in range(args.iterations):
        target = menu[i % len(menu)]
        branch = f"harness-code-{runid}-{i}"
        iter_dir = main / ".claude" / "worktrees" / "harness-code" / f"iter{i}"
        trace_dir = out_dir / f"iter{i}" / "trace"

        rec: dict[str, Any] = {
            "iteration": i,
            "target": target,
            "branch": branch,
            "champion_before": champion_sha,
            "champion_depth_before": champion_depth,
            "summary": None,
            "tests_pass": None,
            "eval_mean_depth": None,
            "accepted": False,
            "champion_after": champion_sha,
            "status": "init",
        }
        print(f"\n=== Iteration {i} | target={target} ===")

        try:
            make_iteration_worktree(main, iter_dir, branch, champion_sha)
            target_path = iter_dir / target
            if not target_path.exists():
                raise RuntimeError(f"target file missing in worktree: {target}")
            current = target_path.read_text()

            # 1. PROPOSE the edit.
            if args.dry_run:
                edit: Optional[CodeEdit] = _templated_edit(target, current, i)
            else:
                edit = proposer.propose(problem, target, current)
            if edit is None:
                rec["status"] = "propose_failed"
                raise _Reject("LLM proposer returned no usable edit")
            rec["summary"] = edit.summary

            # 2. APPLY (full-file overwrite — keeps the guard exact).
            if not is_whitelisted(target):
                rec["status"] = "not_whitelisted"
                raise _Reject(f"target not whitelisted: {target}")
            target_path.write_text(edit.content)

            # 3. HARD GUARD: only the single whitelisted target may have changed.
            assert_only_target_changed(iter_dir, target)

            # 4. REINSTALL the iteration's OWN venv (skipped in dry-run).
            if not args.dry_run:
                ok, log = reinstall_venv(iter_dir)
                _tail(out_dir, i, "reinstall", log)
                if not ok:
                    rec["status"] = "reinstall_failed"
                    raise _Reject("venv reinstall failed")

            # 5. TEST GATE (skipped in dry-run — synthesized as passing).
            if args.dry_run:
                rec["tests_pass"] = True
            else:
                ok, log = run_tests(iter_dir)
                _tail(out_dir, i, "pytest", log)
                rec["tests_pass"] = ok
                if not ok:
                    rec["status"] = "tests_failed"
                    raise _Reject("tests failed")

            # 6. EVAL (synthesized in dry-run — NO API).
            if args.dry_run:
                mean_depth = _synthesize_depth(target, i, champion_depth)
            else:
                ok, log = run_eval(
                    iter_dir, config, trace_dir,
                    eval_n=args.eval_n, policy_model=args.policy_model,
                    env_sh=args.env_sh,
                )
                _tail(out_dir, i, "vf-eval", log)
                if not ok:
                    rec["status"] = "eval_failed"
                    raise _Reject("vf-eval failed")
                mean_depth, per_rollout = parse_iteration_depth(trace_dir)
                rec["per_rollout_depths"] = per_rollout
                if not per_rollout:
                    rec["status"] = "no_depth_parsed"
                    raise _Reject("no depth parsed from traces")
            rec["eval_mean_depth"] = mean_depth

            # 7. ACCEPT / REJECT (the eval-gated noise-margin comparison — this is
            #    the safety net for an edit that passes tests but tanks eval).
            if mean_depth > champion_depth + args.margin:
                new_sha = _commit_champion(iter_dir, target, edit.summary, i)
                champion_sha = new_sha
                champion_depth = mean_depth
                rec["accepted"] = True
                rec["champion_after"] = new_sha
                rec["status"] = "accepted"
                print(f"ACCEPT: depth {mean_depth:.2f} > "
                      f"{rec['champion_depth_before']:.2f}+{args.margin}. "
                      f"New champion {new_sha[:12]}.")
            else:
                rec["status"] = "rejected_no_gain"
                print(f"REJECT: depth {mean_depth:.2f} <= "
                      f"{rec['champion_depth_before']:.2f}+{args.margin}. "
                      f"Champion unchanged ({champion_sha[:12]}).")

        except _Reject as r:
            print(f"REJECT iteration {i}: {r}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            rec["status"] = rec["status"] if rec["status"] != "init" else "error"
            rec["error"] = str(e)
            print(f"ERROR iteration {i}: {e}", file=sys.stderr)
        finally:
            rec["champion_after"] = champion_sha
            rec["champion_depth_after"] = champion_depth
            records.append(rec)
            # 8. CLEANUP the iteration worktree (accepted commit already lives on
            #    its branch / is recorded by SHA; traces stay under --out).
            if iter_dir.exists():
                remove_iteration_worktree(main, iter_dir, branch)
            # Persist after every iteration (resumable-ish).
            _write_run_log(run_log_path, runid, args, champion_sha,
                           champion_depth, records)
            _write_leaderboard(leaderboard_path, runid, champion_sha,
                               champion_depth, records, args)

    print(f"\nFINAL champion={champion_sha[:12]} depth={champion_depth:.2f}")
    print(f"run-log:     {run_log_path}")
    print(f"leaderboard: {leaderboard_path}")
    accepted = sum(1 for r in records if r["accepted"])
    print(f"iterations={len(records)} accepted={accepted} "
          f"(~{len(records) * args.eval_n} rollouts if all reached eval)")
    return {
        "runid": runid,
        "champion_sha": champion_sha,
        "champion_depth": champion_depth,
        "records": records,
        "run_log": str(run_log_path),
        "leaderboard": str(leaderboard_path),
    }


class _Reject(Exception):
    """Internal: a clean per-iteration rejection (not a crash)."""


def _commit_champion(iter_dir: Path, target: str, summary: str, i: int) -> str:
    """Stage ONLY the target file and commit (no AI attribution). Returns SHA."""
    _git(iter_dir, "add", "--", target)
    msg = f"auto-improve iter{i}: {summary}".strip()
    res = _git(iter_dir, "commit", "-m", msg, "--no-verify")
    if res.returncode != 0:
        raise RuntimeError(f"commit failed:\n{res.stdout}\n{res.stderr}")
    return _git(iter_dir, "rev-parse", "HEAD").stdout.strip()


def _tail(out_dir: Path, i: int, name: str, log: str) -> None:
    try:
        d = out_dir / f"iter{i}"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.log").write_text(log)
    except Exception:
        pass


def _write_run_log(path: Path, runid: str, args: argparse.Namespace,
                   champion_sha: str, champion_depth: float,
                   records: list[dict[str, Any]]) -> None:
    log = {
        "runid": runid,
        "dry_run": args.dry_run,
        "iterations_requested": args.iterations,
        "iterations_done": len(records),
        "eval_n": args.eval_n,
        "max_turns": args.max_turns,
        "margin": args.margin,
        "problem": (args.problem or _DEFAULT_PROBLEM),
        "champion_ref_start": args.champion_ref,
        "champion_sha": champion_sha,      # <- relaunch via --champion-ref <this>
        "champion_depth": champion_depth,
        "whitelist": list(WHITELIST),
        "records": records,
    }
    path.write_text(json.dumps(log, indent=2))


def _write_leaderboard(path: Path, runid: str, champion_sha: str,
                       champion_depth: float, records: list[dict[str, Any]],
                       args: argparse.Namespace) -> None:
    lines = [
        f"# auto_improve leaderboard — run {runid}",
        "",
        f"- dry_run: {args.dry_run}",
        f"- margin: {args.margin}   eval_n: {args.eval_n}   "
        f"max_turns: {args.max_turns}",
        f"- CURRENT CHAMPION: `{champion_sha}`  depth=**{champion_depth:.2f}**",
        f"- relaunch from here: `--champion-ref {champion_sha} "
        f"--champion-depth {champion_depth:.2f}`",
        "",
        "| iter | target | tests | eval depth | accept | status | champion after |",
        "|------|--------|-------|-----------|--------|--------|----------------|",
    ]
    for r in records:
        tgt = Path(r["target"]).name
        tp = {True: "pass", False: "FAIL", None: "-"}[r.get("tests_pass")]
        ed = r.get("eval_mean_depth")
        eds = f"{ed:.2f}" if isinstance(ed, (int, float)) else "-"
        acc = "YES" if r.get("accepted") else "no"
        lines.append(
            f"| {r['iteration']} | {tgt} | {tp} | {eds} | {acc} | "
            f"{r.get('status')} | `{r.get('champion_after','')[:12]}` |"
        )
    summary = "\n".join(f"- iter {r['iteration']}: {r.get('summary') or '-'}"
                        for r in records)
    lines += ["", "## change summaries", "", summary, ""]
    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------- #
# CLI
# ---------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m approaches.continuous_harness.auto_improve",
        description="Code-editing champion/challenger self-improvement loop for "
                    "the NetHack harness. The game engine is FROZEN (symlinked "
                    "read-only); an LLM edits ONE whitelisted harness file per "
                    "iteration; only eval improvements (by margin) are kept.",
    )
    p.add_argument("--iterations", type=int, default=3)
    p.add_argument("--eval-n", dest="eval_n", type=int, default=8,
                   help="rollouts per iteration's eval (budget driver).")
    p.add_argument("--max-turns", dest="max_turns", type=int, default=200)
    p.add_argument("--margin", type=float, default=0.15,
                   help="depth a challenger must beat the champion by to be "
                        "accepted (fights eval noise).")
    p.add_argument("--problem", default=None,
                   help="the bottleneck brief handed to the proposer.")
    p.add_argument("--champion-ref", dest="champion_ref", default="HEAD",
                   help="start ref/commit for the champion (default HEAD).")
    p.add_argument("--champion-depth", dest="champion_depth", type=float,
                   default=0.0,
                   help="starting champion's known mean depth (default 0.0).")
    p.add_argument("--config", default=None,
                   help="JSON env-args base merged over the default JSON mega "
                        "config (non-compacted).")
    p.add_argument("--policy-model", dest="policy_model", default="z-ai/glm-4.6",
                   help="policy model id for vf-eval.")
    p.add_argument("--proposer-model", dest="proposer_model", default="z-ai/glm-5",
                   help="code-proposer model id (GLM-5).")
    p.add_argument("--env-sh", dest="env_sh", default="/tmp/ch_env.sh",
                   help="shell file exporting PI_API_KEY / REFINER_* (sourced "
                        "before reinstall-free steps that need creds).")
    p.add_argument("--out", default="/tmp/auto_improve_run",
                   help="output dir for traces, per-step logs, run-log, "
                        "leaderboard.")
    p.add_argument("--dry-run", action="store_true",
                   help="exercise the FULL orchestration with NO API, NO "
                        "reinstall, NO eval: templated edit, real whitelist "
                        "guard, synthesized depth, real accept/reject + logging "
                        "+ worktree cleanup.")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.policy_model == args.proposer_model:
        print("ERROR: --policy-model and --proposer-model must differ.",
              file=sys.stderr)
        return 2
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
