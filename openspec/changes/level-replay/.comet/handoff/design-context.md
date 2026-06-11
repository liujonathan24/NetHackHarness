# Comet Design Handoff

- Change: level-replay
- Phase: design
- Mode: compact
- Context hash: 7a443f52dca213e6f5d11c063ad6790dce42becfcbb0d98bf07471421e822018

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/level-replay/proposal.md

- Source: openspec/changes/level-replay/proposal.md
- Lines: 1-34
- SHA256: 923ab67dbd456ace7d859be9666cf9b2a626f9348573194a1c542a0e869a3be1

```md
## Why

The `custom-nethack-engine` migration built the whole engine foundation — the fork submodule, the `_engine` ctypes binding, `EngineEnv`, `nle_tune_t` difficulty knobs, snapshot/restore, and GATE A golden-trace parity — but stopped short of the migration's actual goal: **the harness still `import nle`, and `nle>=1.3.0` + `minihack` are still hard dependencies.** The engine binding runs *alongside* nle rather than replacing it. `level-replay` finishes the migration: it makes the fork engine canonical, removes nle and MiniHack, and lands the two capabilities the foundation enabled but never wired up — loading custom levels and deterministic replay via snapshot/restore.

## What Changes

- **Make `EngineEnv` the canonical environment.** Rewrite `NetHackCoreEnv.seed/reset/step` (and `skills.py` action mapping + `last_observation`/`_observation_keys` reads) to drive `_engine`, building `CoreObservation` from the binding buffers. Keep `observations.py` `shape()` and `StructuredObservation` field/type parity. **BREAKING** (the env backend changes).
- **Remove `nle`.** Delete the `import nle` code path and drop `nle>=1.3.0` from every `pyproject.toml`/lockfile. Update `Dockerfile.prime` to build the submodule instead of installing the nle wheel. Gated on GATE A parity + determinism, which already pass.
- **Level loading (`nle_load_level`).** Add the fork C API to load a custom level/scenario description, exposed through the binding and `EngineEnv`. **(fork C change → submodule)**
- **Curriculum migration off MiniHack.** Re-express the curriculum tiers' MiniHack `des_file`s via `nle_load_level` (or snapshot presets), confirm tiers run without MiniHack, and **drop the `minihack` git dependency**. **BREAKING** (curriculum backend).
- **Replay via snapshot/restore.** Replace `legacy/replay.py` action-replay internals with snapshot/restore, preserving the trajectory surface the replay viewer consumes.
- **Remaining generation knobs.** Wire the rest of Pillar 2 (`mob_spawn` / `trap_density` / `locked_door` / `corridor_connectivity` / `room_size`) into their `mklev` read-sites; settability + smoke where obs-effect isn't observable. **(fork C change → submodule)**
- **End-to-end eval smoke + docs.** A full eval run through the new engine; document the engine layer (binding, snapshot API, tune knobs with ranges/timing, level format) and record the open-question resolutions.

## Capabilities

### New Capabilities
<!-- none new; this change advances capabilities introduced by custom-nethack-engine -->

### Modified Capabilities
- `nethack-engine`: the fork `_engine` binding becomes the sole backend; `nle` removed; `EngineEnv` canonical.
- `level-customization`: adds `nle_load_level` and the MiniHack-curriculum migration (drop `minihack`); resolves the preset/level format (OQ4).
- `difficulty-tuning`: adds the remaining map-generation knobs (mob/trap/door/corridor/room_size).
- `replay-viewer`: replay backed by engine snapshot/restore instead of nle action-replay.

> These capabilities currently live as **delta specs in the still-active `custom-nethack-engine` change** (not yet archived to `openspec/specs/`). `level-replay` extends the same capabilities and absorbs the remaining open tasks of `custom-nethack-engine`; the two will be reconciled at archive (deltas sync in order).

## Impact

- **Code:** `nethack_core/env.py` (drop nle, drive `_engine`), `skills.py`, `observations.py` (parity check), `legacy/replay.py`, `nethack_core/_engine.py` + `engine_env.py` (expose `load_level`), curriculum tier definitions.
- **Fork C (submodule):** `nle_load_level` + remaining knob read-sites in `mklev`/spawn; harness bumps the `third_party/NetHack` submodule pointer after the fork PR merges.
- **Dependencies (removed):** `nle>=1.3.0`, `minihack` from `nethack_core/pyproject.toml` + lockfiles.
- **Build/CI:** `Dockerfile.prime` builds the submodule (no nle wheel); README/dev docs document `--recurse-submodules` + build.
- **Gates:** GATE A (parity) and determinism already pass and gate the nle removal; a full eval smoke validates the cutover end-to-end.
```

## openspec/changes/level-replay/design.md

- Source: openspec/changes/level-replay/design.md
- Lines: 1-38
- SHA256: 1f708e10807d8c68076ee9123acb8e645ed0459cfbda4346670dbd0854b4a151

```md
## High-level approach

This change finishes the migration. The risky pieces (parity, snapshot) are already done and green, so the work is integration + removal, sequenced so the harness never has two live backends at once.

### Decision 1 — `EngineEnv` becomes canonical; don't keep two env classes

Rather than rewrite `NetHackCoreEnv` in place against `import nle`, fold it onto the existing `EngineEnv`. Approach: make `NetHackCoreEnv` delegate to `EngineEnv` (thin adapter preserving the public `seed/reset/step` + observation surface), then delete the nle-backed internals. This keeps `observations.py shape()` and `StructuredObservation` consumers unchanged — parity is asserted by a field/type test against the pre-cutover shape. Action mapping in `skills.py` moves to the engine's keypress action space (already validated identity-ish by GATE A).

### Decision 2 — remove nle only behind the green gates, in one commit

GATE A (structured parity) and determinism already pass. The nle removal (`import nle` deletion + `nle>=1.3.0` drop from pyproject/lock + `Dockerfile.prime`) lands as one reviewable cutover commit, *after* the env/skills/replay swap, so the diff that removes nle is the diff that proves nothing else imports it. A repo-wide `grep -rn "import nle\|from nle\|minihack"` must come back clean (outside archived/legacy docs) as the cutover's acceptance check.

### Decision 3 — level loading: extend the existing tune-at-start plumbing

`nle_load_level` follows the same "set before `mklev`" pattern already used for generation knobs (the starting level is built inside `nle_start`). The fork adds a level-source override to `nle_settings`/`nle_start`; the binding exposes `load_level(...)` on `RawEngine`/`EngineEnv`. The preset/level format (OQ4) is decided here — likely reuse NetHack `des` description files the fork can already parse, bundled as harness assets, so the MiniHack curriculum tiers re-express directly.

### Decision 4 — replay rides on snapshot/restore, not action re-execution

`legacy/replay.py` currently re-executes recorded actions through nle. Swap to: snapshot at episode start (and optionally at checkpoints), restore + step to scrub. The trajectory surface the replay viewer consumes (`replay-viewer` capability) stays the same shape; only the producer changes.

### Decision 5 — generation knobs: settability-first

The remaining Pillar 2 knobs (mob/trap/door/corridor/room_size) mostly affect off-screen/hidden state, so they aren't obs-effect-testable like `room_density` was. Wire each to its `mklev`/spawn read-site, and gate them with settability + smoke tests (no crash, value round-trips, floor still generates) rather than obs-diff assertions. Honestly mark which are visually demoable.

## Sequencing & gates

1. Fork C: `nle_load_level` + remaining knob read-sites → fork PR → bump submodule.
2. Binding: expose `load_level`; harness: env/skills/replay swap onto `EngineEnv`.
3. Cutover: remove nle + minihack; Docker; curriculum re-expressed.
4. Verify: parity/determinism still green, full eval smoke end-to-end, docs.

Hard gates (unchanged from the parent migration): GATE A parity and determinism must stay green across the cutover. Two-repo rule: engine C → fork branch + PR; harness only bumps the submodule pointer.

## Open questions (resolve in deep design / brainstorming)

- OQ4: exact preset/level format and where curriculum assets live.
- Replay back-compat: do existing recorded `.ndjson`/trajectories need a migration, or is replay forward-only from the cutover?
- Curriculum parity: how to confirm re-expressed tiers match the MiniHack originals (golden level dumps? behavioral smoke?).
```

## openspec/changes/level-replay/tasks.md

- Source: openspec/changes/level-replay/tasks.md
- Lines: 1-43
- SHA256: ac164fce064658f44ea5fd3bc4ce04b080c93772935b70c2ee2b6b2512cb31bb

```md
# Tasks — level-replay

> Finishes the `custom-nethack-engine` migration. Absorbs that change's remaining open
> tasks (§3.5, §5, §6, §7.5–7.6, §2.3–2.4, §8, Pillar 2 knobs).

## 1. Fork C API (submodule → fork branch + PR)
- [ ] 1.1 `nle_load_level(ctx, ...)` — load a custom level/scenario description; apply before `mklev` via the existing `nle_settings`/`nle_start` tune-at-start plumbing
- [ ] 1.2 Wire remaining Pillar 2 generation knobs to their `mklev`/spawn read-sites: `mob_spawn`, `trap_density`, `locked_door`, `corridor_connectivity`, `room_size`
- [ ] 1.3 Open the fork PR; after merge, bump the `third_party/NetHack` submodule pointer in the harness

## 2. Binding surface (`_engine` / `EngineEnv`)
- [ ] 2.1 Expose `load_level(...)` on `RawEngine` and `EngineEnv` (closes custom-nethack-engine §4.4 partial)
- [ ] 2.2 Expose the new generation knobs through the tune surface; assert they round-trip
- [ ] 2.3 Tests: `load_level` loads the expected layout; new knobs are settable + safe (no crash, floor still generates)

## 3. Make `EngineEnv` canonical (harness integration)
- [ ] 3.1 `NetHackCoreEnv.seed/reset/step` delegate to `EngineEnv`; build `CoreObservation` from binding buffers
- [ ] 3.2 Verify `observations.py` `shape()` + `StructuredObservation` field/type parity vs the pre-cutover shape (parity test)
- [ ] 3.3 Update `skills.py` action-index mapping + `last_observation`/`_observation_keys` reads to the binding
- [ ] 3.4 Snapshot/restore + tune surface available on the canonical env (delegated from `EngineEnv`)

## 4. Replay via snapshot/restore
- [ ] 4.1 Replace `legacy/replay.py` action-replay internals with snapshot/restore (snapshot at start/checkpoints, restore+step to scrub)
- [ ] 4.2 Preserve the trajectory surface the replay viewer consumes; decide recorded-trajectory back-compat (forward-only vs migration)
- [ ] 4.3 Test: a recorded episode replays to the same per-turn observations via restore

## 5. Level customization + curriculum migration
- [ ] 5.1 Decide + document the preset/level format and where curriculum assets live (resolves OQ4)
- [ ] 5.2 Re-express the curriculum tiers' MiniHack `des_file`s via `nle_load_level` (or snapshot presets)
- [ ] 5.3 Confirm tiers run without MiniHack; check re-expressed tiers match the originals (level dump or behavioral smoke)
- [ ] 5.4 Remove the `minihack` git dependency from `pyproject.toml` + lockfiles

## 6. The nle cutover
- [ ] 6.1 Delete the `import nle` code path from `nethack_core` (env.py / __init__.py)
- [ ] 6.2 Remove `nle>=1.3.0` from every `pyproject.toml` + lockfile; `uv sync` resolves clean without it
- [ ] 6.3 Repo-wide acceptance check: `grep -rn "import nle\|from nle\|minihack"` is clean outside archived/legacy docs
- [ ] 6.4 Update `Dockerfile.prime` to build the submodule (`build_engine.sh`) instead of installing the nle wheel

## 7. Verify + docs
- [ ] 7.1 GATE A golden-trace parity + determinism still green after the cutover
- [ ] 7.2 Full eval smoke run end-to-end through the new engine
- [ ] 7.3 Document the engine layer: binding, snapshot API, tune knobs (ranges + timing), level format; `--recurse-submodules` clone + build steps in README/dev docs
- [ ] 7.4 Record open-question resolutions (OQ4 + final API signatures); mark the absorbed `custom-nethack-engine` tasks as superseded-by `level-replay`
```

