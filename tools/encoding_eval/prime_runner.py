"""Real `runner(cell)` for `run_matrix` that drives `prime eval run`.

This is the operational wiring the README ("Running a real benchmark") leaves to
the operator. It:

  1. Maps a matrix cell ``{variant, map_detail, model}`` to a ``prime eval run``
     invocation against the local ``nethack`` verifiers env.
  2. Forces the *current* worktree env onto ``sys.path`` via ``PYTHONPATH`` so
     ``import nethack`` resolves to this code rather than any stale
     ``site-packages/nethack.py`` shim (there is a real name collision — the
     Prime hub publishes this env as the bare module ``nethack``).
  3. Points the env's ``trace_dir`` at ``<run_dir>/<cell>/`` so per-turn NDJSON
     traces (with ``rendered_user_content`` + image refs) are captured for
     ``replay.render_replay``.
  4. Builds per-rollout sample dicts from those traces (one file per rollout),
     attaches the trace, and returns them for ``aggregate.aggregate_cells``.

Why trace-derived samples instead of ``load_hosted_eval_samples``?
  ``prime eval run`` executes locally and (when it completes) writes
  ``results.jsonl`` locally; the *hosted* sample API (``prime eval get``) only
  has data after a separate ``prime eval push``. The NDJSON trace is the richest
  always-local source and is exactly what the replay viewer consumes, so we read
  it directly. If a local ``results.jsonl`` is present we prefer its scalar
  rubric rewards (descent_reward etc.) and fall back to deriving descent from the
  trace's max dungeon level.

Model selection: text encodings (B1/JSON/TOON) use the instruct model from
``configs/eval/qwen-3-5.toml``; pixel encodings (IMG/IMG_TTY) use the VLM. The
cell's explicit ``model`` overrides both.

NOTE (env caveat, see is_completed fix in nethack.py): ``max_turns`` is the
per-rollout LM-call cap. Rollout length is *also* bounded by the curriculum
tier's ``max_episode_steps`` (in-game NLE steps); pick a ``tier`` whose budget is
large enough that ``max_turns`` is the binding constraint.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

# Repo layout: this file is tools/encoding_eval/prime_runner.py
_REPO = Path(__file__).resolve().parents[2]
_ENV_DIR = _REPO / "environments" / "nethack"

# Pixel encodings need a vision model; text encodings use the instruct model.
_PIXEL_VARIANTS = {"IMG", "IMG_TTY"}
# Verified available on Prime Inference (2026-06). The TOML default
# "Qwen/Qwen3.5-VL-7B" does NOT exist on the platform — closest real VLM is
# qwen/qwen3-vl-8b-instruct.
_DEFAULT_INSTRUCT_MODEL = "Qwen/Qwen3.5-4B"
_DEFAULT_VLM_MODEL = "qwen/qwen3-vl-8b-instruct"


def _cell_dir_name(cell: dict) -> str:
    v = cell["variant"]
    md = cell.get("map_detail")
    return f"{v}__{md}" if md else v


def _model_for_cell(cell: dict) -> str:
    if cell.get("model"):
        return cell["model"]
    return _DEFAULT_VLM_MODEL if cell["variant"] in _PIXEL_VARIANTS else _DEFAULT_INSTRUCT_MODEL


def build_command(
    cell: dict,
    *,
    run_dir: Path,
    num_examples: int,
    rollouts_per_example: int,
    max_tokens: int,
    max_turns: int,
    tier: str,
    n_examples: int,
    provider: str = "prime",
) -> tuple[list[str], dict, Path]:
    """Return (argv, env, trace_dir) for a single cell — pure, no side effects."""
    trace_dir = run_dir / _cell_dir_name(cell)
    env_args = {
        "variant": cell["variant"],
        "trace_dir": str(trace_dir),
        "max_turns": max_turns,
        "tier": tier,
        "n_examples": n_examples,
    }
    if cell.get("map_detail"):
        env_args["map_detail"] = cell["map_detail"]

    argv = [
        "prime", "eval", "run", "nethack",
        "--model", _model_for_cell(cell),
        "--provider", provider,
        "--num-examples", str(num_examples),
        "--rollouts-per-example", str(rollouts_per_example),
        "--max-concurrent", "1",
        "--max-tokens", str(max_tokens),
        "--env-args", json.dumps(env_args),
        "--output-dir", str(trace_dir / "eval_out"),
        "--save-results",
        "--disable-tui",
    ]
    proc_env = dict(os.environ)
    # Prepend the worktree env dir so `import nethack` -> current code.
    proc_env["PYTHONPATH"] = os.pathsep.join(
        [str(_ENV_DIR)] + ([proc_env["PYTHONPATH"]] if proc_env.get("PYTHONPATH") else [])
    )
    proc_env["PRIME_DISABLE_VERSION_CHECK"] = "1"
    return argv, proc_env, trace_dir


# Prime Inference $/1M tokens (input, output). Extend as needed.
_PRICES = {
    "Qwen/Qwen3.5-4B": (0.1, 0.3),
    "qwen/qwen3-vl-8b-instruct": (0.18, 0.7),
}


def _load_traces(trace_dir: Path) -> list[list[dict]]:
    out = []
    for f in sorted(trace_dir.glob("*.ndjson")):
        rows = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
        if rows:
            out.append(rows)
    return out


def _find_results_jsonl(trace_dir: Path) -> Optional[Path]:
    hits = sorted((trace_dir / "eval_out").rglob("results.jsonl"))
    return hits[-1] if hits else None


def _cost_dollars(token_usage: dict, model: str) -> Optional[float]:
    pin, pout = _PRICES.get(model, (None, None))
    if pin is None:
        return None
    return (float(token_usage.get("input_tokens", 0)) * pin
            + float(token_usage.get("output_tokens", 0)) * pout) / 1_000_000.0


def _samples_from_results(trace_dir: Path, model: str) -> list[dict]:
    """Load prime's local results.jsonl rows as samples (proper rubric rewards),
    enrich with tokens_per_turn + dollars, and attach the matching NDJSON trace.

    results.jsonl rows already carry reward / descent_reward / scout_reward /
    info / is_truncated exactly as summarize_eval expects. Traces are matched by
    sorted order (one trace file per rollout)."""
    res = _find_results_jsonl(trace_dir)
    if res is None:
        return []
    rows = [json.loads(l) for l in res.read_text().splitlines() if l.strip()]
    traces = _load_traces(trace_dir)
    samples = []
    for i, r in enumerate(rows):
        tu = r.get("token_usage") or {}
        nturns = float(r.get("num_turns") or 0) or 1.0
        tot_tok = float(tu.get("input_tokens", 0)) + float(tu.get("output_tokens", 0))
        r["tokens_per_turn"] = tot_tok / nturns if tot_tok else None
        r["dollars"] = _cost_dollars(tu, model)
        if i < len(traces):
            r["trace"] = traces[i]
            r["max_dlvl"] = max((int((e.get("status") or {}).get("depth", 0) or 0)
                                 for e in traces[i]), default=0)
        samples.append(r)
    return samples


def _sample_from_trace(trace: list[dict], seed: Optional[int]) -> dict:
    max_dlvl = max((int((e.get("status") or {}).get("depth", 0) or 0) for e in trace), default=0)
    final_reward = float(trace[-1].get("reward", 0.0) or 0.0)
    # The per-turn trace carries the cumulative `reward`, not the rubric's
    # scalar `descent_reward`; derive descent from depth progression (dlvl>=2).
    return {
        "seed": seed,
        "example_id": seed,
        "trace": trace,
        "reward": final_reward,
        "descent_reward": 1.0 if max_dlvl >= 2 else 0.0,
        "max_dlvl": max_dlvl,
        "info": {"is_completed": False, "is_truncated": True},
        "tokens_per_turn": None,
        "dollars": None,
    }


def make_runner(
    *,
    run_dir: str | Path,
    num_examples: int = 1,
    rollouts_per_example: int = 1,
    max_tokens: int = 512,
    max_turns: int = 200,
    tier: str = "corridor_explore",
    n_examples: int = 8,
    provider: str = "prime",
    timeout_s: int = 1800,
    dry_run: bool = False,
):
    """Build a ``runner(cell) -> list[sample]`` closure for ``run_matrix``.

    ``dry_run=True`` skips the (cost-incurring) ``prime eval run`` and only loads
    whatever traces already exist under the cell dir — useful for re-aggregating.
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    def runner(cell: dict) -> list[dict]:
        argv, proc_env, trace_dir = build_command(
            cell, run_dir=run_dir, num_examples=num_examples,
            rollouts_per_example=rollouts_per_example, max_tokens=max_tokens,
            max_turns=max_turns, tier=tier, n_examples=n_examples, provider=provider,
        )
        trace_dir.mkdir(parents=True, exist_ok=True)
        if not dry_run:
            log = trace_dir / "run.log"
            with log.open("w") as lf:
                subprocess.run(argv, env=proc_env, stdout=lf, stderr=subprocess.STDOUT,
                               timeout=timeout_s, check=False)
        # Prefer prime's local results.jsonl (proper rubric rewards + token
        # usage); fall back to deriving samples from the NDJSON traces if the
        # run did not complete cleanly enough to write results.
        samples = _samples_from_results(trace_dir, _model_for_cell(cell))
        if not samples:
            for trace in _load_traces(trace_dir):
                seed = (trace[0].get("status") or {}).get("seed")
                samples.append(_sample_from_trace(trace, seed))
        return samples

    return runner


if __name__ == "__main__":  # pragma: no cover - manual operational entrypoint
    import argparse
    from tools.encoding_eval.run import run_matrix
    from tools.encoding_eval.aggregate import table_to_markdown

    p = argparse.ArgumentParser(description="Run the encoding-eval matrix via prime eval.")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--num-examples", type=int, default=1)
    p.add_argument("--rollouts-per-example", type=int, default=1)
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--max-turns", type=int, default=200)
    p.add_argument("--tier", default="corridor_explore")
    p.add_argument("--n-examples", type=int, default=8)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    matrix = {
        "encodings": [
            {"variant": "B1", "map_detail": None},
            {"variant": "JSON", "map_detail": "full"},
            {"variant": "TOON", "map_detail": "full"},
            {"variant": "IMG", "map_detail": None},
            {"variant": "IMG_TTY", "map_detail": None},
        ],
        "models": [None],  # None -> auto (instruct for text, VLM for pixels)
    }
    runner = make_runner(
        run_dir=args.run_dir, num_examples=args.num_examples,
        rollouts_per_example=args.rollouts_per_example, max_tokens=args.max_tokens,
        max_turns=args.max_turns, tier=args.tier, n_examples=args.n_examples,
        dry_run=args.dry_run,
    )
    table = run_matrix(matrix, runner=runner)
    out = Path(args.run_dir)
    (out / "table.json").write_text(json.dumps(table, indent=2, default=str))
    (out / "table.md").write_text(table_to_markdown(table) + "\n")
    print(table_to_markdown(table))
