# mc_replay — Monte-Carlo lookahead / branch tool

A small tool that evaluates candidate next actions on a NetHack engine state by
**branching the live engine** with Monte-Carlo rollouts, then ranking the
candidates by an expected score. This is "checking ahead": before committing to
a move, branch it `n_branches` times, roll out a policy for a `horizon`, and see
which candidate looks most promising.

## What it does

`mc_lookahead(env, candidate_actions, *, horizon=40, n_branches=3, reseed=True,
score_fn=None, rollout_policy=None)`:

1. Snapshots the env's **current** state once.
2. For each candidate action, runs `n_branches` rollouts. Each rollout:
   restore the snapshot → (if `reseed`) reseed the RNG with a per-branch seed →
   step the candidate action → roll out `horizon` steps of a default policy
   (default: repeat the candidate action, or a provided
   `rollout_policy(obs, candidate_action) -> action`) → score the final state.
3. Returns a list of dicts sorted best-first:
   `{"action", "mean_score", "scores", "mean_depth_gain", "death_rate"}`.
4. Frees the snapshot before returning.

The single snapshot handle is **reused across all branches** (RawEngine
snapshots support repeated byte-exact restore) and freed in a `finally`.
Per-branch engine exceptions are caught and scored as a death, so one bad
branch never aborts the whole call.

`replay_then_branch(env, action_prefix, candidate_actions, **kw)`: steps the env
through `action_prefix` from its current state, then calls `mc_lookahead`. This
is the "replay to a point, then Monte-Carlo the continuations" workflow.

Default `score_fn(obs, done)` = dungeon depth (`blstats[12]`) minus a large
death penalty (so candidates that survive and descend outrank ones that die).
Pass your own `score_fn` for a different objective.

## Snapshot / branch basis

Built directly on the fork engine's in-memory branching primitives
(`nethack_core/engine_env.py`, `nethack_core/_engine.py`):

- `snapshot()` captures the full live state (ctx + coroutine stack + arena +
  display mirror) as an opaque handle.
- `restore(handle)` returns the engine to that exact point — **byte-exact** and
  repeatable from the same handle.
- `engine.reseed(core=, disp=)` reseeds the gameplay RNG **after** restore so
  random chance diverges across branches. Order matters: the snapshot captures
  the RNG, so reseed must follow restore (mirrors `EngineEnv.branch()`).

With `reseed=False` branches replay byte-identically (deterministic). With
`reseed=True` branches can diverge as random events differ.

## blstats indices used (verified empirically)

Confirmed by stepping the engine and watching the values move:

| index | meaning  | evidence |
|-------|----------|----------|
| `blstats[0]`  | player x | changes with `h`/`l` (west/east) |
| `blstats[1]`  | player y | changes with `j`/`k` (south/north) |
| `blstats[12]` | depth (dlvl) | starts at 1 on the first floor |

## Run the demo

```bash
uv run python -m tools.mc_replay.demo
```

It constructs an `EngineEnv`, resets with seed 42, walks a few fixed moves into
the dungeon, then runs `mc_lookahead` over the 4 cardinal moves + search +
descend (`>`) with `n_branches=3, horizon=20`, and prints the ranked results
(action, mean_score, mean_depth_gain, death_rate). On a small starting floor the
candidates often tie (all survive on depth 1 within a short horizon) — that is
correct: the scorer only separates candidates once their rollouts actually
differ in depth or death.

## Run the tests

```bash
uv run pytest tools/mc_replay/test_mc.py -q
```

## Scope / follow-up: this is the LIVE-state MC primitive

`mc_lookahead` branches from **whatever state the passed-in `env` is currently
in**. It is the live-state Monte-Carlo primitive.

Deterministically replaying a **saved harness trace** to a point and then
Monte-Carlo'ing the continuations additionally requires that trace's
**per-example seed** — the engine is seed-before-reset, and without the original
`(core, disp)` seeds the replayed state will not match the recorded one. The
current NDJSON harness traces **do not store the per-example seed**, so
trace-seed replay is **not implemented here** and is flagged as a follow-up:
once traces persist their seeds, a thin wrapper can `seed()` + `reset()` +
replay the action prefix, then call `mc_lookahead`.
