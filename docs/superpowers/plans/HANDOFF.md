# Handoff — custom-nethack-engine (execute on Linux)

You're picking up an in-progress, fully-planned initiative in this repo
(NetHackHarness). All design/planning is committed; your job is execution on Linux.

## Goal

Migrate the harness off the `nle` PyPI package to a custom struct-based NetHack
fork (https://github.com/liujonathan24/NetHack), added as a git submodule —
full cutover. Add O(arena) state snapshots, a parametric `nle_tune_t` difficulty
knob catalog, and level customization. The fork is developed by me; engine C
changes go to THAT repo as PRs, the harness only bumps the submodule pointer.

## Start here — read these before doing anything

1. `docs/superpowers/plans/2026-06-10-custom-nethack-engine.md` — the 23-task
   plan. Read its **Execution Environment** and **Two-Repo Workflow** sections FIRST.
2. `docs/superpowers/specs/2026-06-10-custom-nethack-engine-design.md` — design,
   grounded in the actual fork source (verified, not guessed).
3. `openspec/changes/custom-nethack-engine/specs/*/spec.md` — the 4 delta specs,
   incl. the full `nle_tune_t` knob catalog in `difficulty-tuning/spec.md`.

## Current state

- Branch: `custom-nethack-engine` (check it out). 3 commits done:
  planning artifacts → submodule add (`third_party/NetHack` @ `9c7194d`) → plan notes.
- This is a Comet change at `phase=build`, `isolation=branch`,
  `build_mode=subagent-driven-development`. Run `/comet` to auto-resume from the
  plan, OR just execute the plan directly with subagent-driven-development.
- Done: Plan Task 1 (submodule added). Next: Plan Task 2 (build `libnethack.so`).

## Environment

- Must be **Linux x86-64** (the engine is ELF x86-64; it would not load/build on the
  macOS arm64 box where planning happened — that's why execution was handed off).
- Init + build the engine:
  ```
  git submodule update --init --recursive
  make -C third_party/NetHack/src/build nethack -j
  ```
  Paths: headers `third_party/NetHack/src/include/`, C `third_party/NetHack/src/src/`,
  build dir `third_party/NetHack/src/build` (committed `libnethack.so` is x86-64).

## Already verified about the fork (don't re-derive)

- Snapshot primitive EXISTS: `nle_fr_snapshot`/`restore`/`destroy` in
  `src/src/nle_fast_reset.c` (memcpy ctx + coroutine stack + per-env mmap arena;
  pointers valid at fixed base).
- Obs buffer API EXISTS: `struct nle_observation` in `src/include/nleobs.h` — caller
  allocates buffers, `nle_step` fills them. `NLE_BLSTATS_SIZE == 27` (harness assumed 26).
- Seeding EXISTS: `nle_set_seed(ctx, core, disp, reseed)` — use `reseed=0`.
- So the binding is mostly BIND; the NEW C work is `nle_tune_t` + read-sites and
  snapshot→bytes serialization.

## Hard gates (do not skip)

- **GATE A**: golden-trace parity vs a recorded `nle` trace must pass BEFORE removing
  the `nle` dependency (Plan Tasks 6-7 gate Task 11).
- **GATE B**: multi-level snapshot-completeness spike (Plan Task 12) BEFORE finalizing
  the snapshot API. NetHack swaps inactive levels to disk (`goto_level`/`savelev`/`getlev`),
  so the arena snapshot may miss them — bundle `<hackdir>/<s_lock>.*` if the spike fails.

## Two-repo rule

- Engine C changes → fork branch in `third_party/NetHack`, push to the fork remote,
  open a PR to `liujonathan24/NetHack`. NEVER commit fork C diffs into this harness
  repo; here you only bump the submodule pointer (`git add third_party/NetHack`) after
  a fork PR merges.

## Attribution (mandatory)

- I (Jonathan Liu) am the sole author of every commit. Do NOT add `Co-Authored-By`
  trailers, "Generated with Claude Code", or any AI attribution to commits, PRs, or docs.

Confirm before pushing to any remote.
