# harness_loop — self-improving NetHack harness-iteration loop

An automated outer loop that **tunes the harness around an immutable NetHack
game engine**. Each iteration creates a fresh git worktree, runs a
Continual-Harness (CH) rollout/eval inside it, scores the result by dungeon
**depth**, and proposes the next harness config from the last iteration's
result. The loop keeps the best config on a leaderboard.

## The immutable-game invariant

The game engine is **NEVER patched**. The loop only ever changes
`load_environment(...)` kwargs + bootstrap files. Two guards enforce this
(`assert_engine_untouched` in `loop.py`):

1. `third_party/NetHack` inside every iteration worktree must be a **symlink**
   back to the shared engine source — never a real, editable copy.
2. `git status --porcelain` over `third_party/NetHack`, `third_party/nethack`,
   and `nethack_core` must be clean inside the iteration worktree; any change
   fails the iteration.

The loop also never writes under those paths itself.

## The three mutable surfaces

All three map onto existing env knobs — no engine change needed:

| Surface              | Env knob                              | Where |
|----------------------|---------------------------------------|-------|
| observation format   | `variant` (e.g. `B1`,`FD`,`JSON`,`B`,`CH`) | `VARIANT_REGISTRY` |
| tools / skills       | `skill_set` (`full`/`move`/`dir8`/`netplay`/allowlist) | `_build_skill_adapter_callables` |
| prompt + macros + sub-agents + journal | `bootstrap_dir` → `seed<N>.json` | loaded by `variant="CH"` at rollout start |

The bootstrap file is exactly the dict that
`nethack_harness.refiner.snapshot_components(state)` produces:

```json
{
  "prompt_addendum": "<system-prompt addendum>",
  "subagents": { "<name>": { "...": "..." } },
  "skills":    { "<macro-name>": ["<action>", "..."] },
  "notes":     { "<key>": "<text>" },
  "objective": "<pinned objective or null>"
}
```

`HarnessConfig.to_bootstrap_json(seed)` emits this. `macros` → `skills` (values
must be lists), `subagents` → `subagents` (values must be dicts); the env's
`load_components` keeps only list-valued skills and dict-valued subagents.

## Worktree-per-iteration mechanics

Matches how the parent worktree was set up:

```
git worktree add .claude/worktrees/harness-iter/iter<N> -b harness-iter-<runid>-<N> HEAD
ln -s <CURRENT>/third_party/NetHack <ITER>/third_party/NetHack   # engine: symlink, never copy
ln -s <CURRENT>/.venv               <ITER>/.venv                  # shared venv (args-only MVP)
```

Iteration worktrees are auto-removed after results are parsed (traces +
bootstraps + run-log live under `--out`). Pass `--keep-worktrees` to retain them.

## Metric (depth)

Each rollout writes NDJSON turn records under `trace_dir`; each record has
`dlvl` and `max_dlvl_reached`. Per-rollout depth = max `max_dlvl_reached`
(fallback: max `dlvl`). Iteration score = **mean** per-rollout depth across the
N seeds. Mean reward is captured best-effort from vf-eval's saved metadata.

## Run commands

### Dry-run (NO API, NO budget) — orchestration smoke test

```
uv run python -m tools.harness_loop.loop --iterations 2 --dry-run --out /tmp/harness_loop_dryrun
```

Creates 2 iteration worktrees, writes bootstraps, synthesizes deterministic
depths, prints a leaderboard, writes a run-log, and removes the worktrees. The
fallback proposer is forced; no network call is made.

### Real 3-iteration LLM-proposer loop

`/tmp/ch_env.sh` must export `PI_API_KEY`, `REFINER_API_KEY`,
`REFINER_BASE_URL` (Prime Inference). The loop sources it before each eval.

```
uv run python -m tools.harness_loop.loop \
  --iterations 3 \
  --proposer llm \
  --policy z-ai/glm-4.6 \
  --teacher z-ai/glm-5 \
  --tier corridor_explore \
  --seed 0 --n-seeds 1 \
  --max-turns 200 --refine-interval 20 \
  --out /tmp/harness_loop_run
```

Policy and teacher **must differ** (both served by Prime Inference). The base
config uses `variant="CH"` so bootstraps take effect; the LLM proposer (GLM-5)
may switch `variant`/`skill_set` and rewrite the prompt addendum / macros /
sub-agents between iterations.

## CODE-editing loop — `auto_improve.py`

`loop.py` mutates **args + bootstrap only**. `auto_improve.py` extends it into a
**champion/challenger loop that lets an LLM EDIT the harness CODE** (one
whitelisted file per iteration), with the game engine still FROZEN.

Each iteration: branch a worktree off the **champion** commit → symlink the
frozen engine → ask GLM-5 (`code_proposer.CodeProposer`) to return a COMPLETE
replacement of ONE whitelisted file → **HARD guard** → reinstall the iteration's
OWN venv → `pytest` gate → `vf-eval` → ACCEPT iff
`mean_depth > champion_depth + margin` (commit, new champion) else REJECT →
clean up the worktree.

**Editable whitelist** (the ONLY files an iteration may change), in
`code_proposer.WHITELIST`:
`tools/skills.py`, `tools/code_mode.py`, `prompt/rendering.py`,
`prompt/prompt_spec.py`, `prompt/map_encoders.py`,
`navigation/pathfinding.py` (all under `environments/nethack/nethack_harness/`).

**Engine-immutability guard** (`assert_only_target_changed`): the engine dir must
be a symlink; no dirty path under `third_party/**` / `nethack_core/**`; and the
set of changed paths (from `git status --porcelain`, excluding the engine
submodule mount) must be EXACTLY `{target}`, with `target` passing
`is_whitelisted`. Any extra/engine/glue path → the iteration is rejected. Because
the proposer overwrites the WHOLE file, only one path can ever change, making the
guard exact.

**Accept/reject is the safety net** for an edit that passes tests but tanks eval:
tests only prove the package imports + unit-behaves; the eval-gated margin
(default **0.15**) rejects any challenger whose `mean_depth` is not clearly above
the champion, so a test-passing but play-worsening edit never becomes champion.

```
# dry-run (NO API / NO reinstall / NO eval — synthesized depth):
uv run python -m tools.harness_loop.auto_improve --iterations 2 --dry-run \
    --out /tmp/auto_improve_dry

# real (supervisor; ~eval_n rollouts + one venv reinstall per iteration):
source /tmp/ch_env.sh && uv run python -m tools.harness_loop.auto_improve \
    --iterations 10 --eval-n 8 --max-turns 200 --margin 0.15 \
    --problem "navigation + obs: agent under-descends; route to stairs/frontier" \
    --out /tmp/auto_improve_run
```

The run-log records `champion_sha`; relaunch with
`--champion-ref <sha> --champion-depth <depth>` to resume from the best harness.
```
