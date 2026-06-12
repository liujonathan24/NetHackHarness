# Comet Design Handoff

- Change: level-replay
- Phase: design
- Mode: compact
- Context hash: 5f0c1440813aabbfad5ee41a56ebee8fdef12702fa86e97b83c43aa9e0681108

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/level-replay/proposal.md

- Source: openspec/changes/level-replay/proposal.md
- Lines: 1-35
- SHA256: 1df738f34e6bb1ceb344d6b9745bc38796f98aec98aeff69080282bad18e8a39

```md
## Why

The `custom-nethack-engine` migration built the whole engine foundation — the fork submodule, the `_engine` ctypes binding, `EngineEnv`, `nle_tune_t` difficulty knobs, snapshot/restore, and GATE A golden-trace parity — but stopped short of the migration's actual goal: **the harness still `import nle`, and `nle>=1.3.0` + `minihack` are still hard dependencies.** The engine binding runs *alongside* nle rather than replacing it. `level-replay` finishes the migration: it makes the fork engine canonical, removes nle and MiniHack, and lands the two capabilities the foundation enabled but never wired up — loading custom levels and deterministic replay via snapshot/restore.

## What Changes

- **Make `EngineEnv` the canonical environment.** Rewrite `NetHackCoreEnv.seed/reset/step` (and `skills.py` action mapping + `last_observation`/`_observation_keys` reads) to drive `_engine`, building `CoreObservation` from the binding buffers. Keep `observations.py` `shape()` and `StructuredObservation` field/type parity. **BREAKING** (the env backend changes).
- **Remove `nle`.** Delete the `import nle` code path and drop `nle>=1.3.0` from every `pyproject.toml`/lockfile. Update `Dockerfile.prime` to build the submodule instead of installing the nle wheel. Gated on GATE A parity + determinism, which already pass.
- **Level-file-blob model (generate / save / load).** Floors are generated natively (seed + knobs); `nle_save_level` dumps the current floor to a portable `savelev`/`getlev` blob and `nle_load_level` starts on a saved floor, surfaced as `EngineEnv.save_level/load_level` against a floor-library dir. **(fork C change → submodule)**
- **Curriculum migration off MiniHack.** Compile the 3 static des tiers once to level blobs (des → `lev_comp` → save); native tiers stay native; confirm tiers run without MiniHack and **drop the `minihack` git dependency**. **BREAKING** (curriculum backend).
- **Snapshot + explore.** Replace `legacy/replay.py` `(seed, actions)` re-execution with snapshot/restore, and add `EngineEnv.branch(n, reseed=True)` — N divergent continuations from a snapshot (reseed-after-restore so random-chance events vary). The replay *viewer* (stored-trace timeline) is unaffected.
- **Remaining generation knobs.** Wire the rest of Pillar 2 (`mob_spawn` / `trap_density` / `locked_door` / `corridor_connectivity` / `room_size`) into their `mklev` read-sites; settability + smoke where obs-effect isn't observable. **(fork C change → submodule)**
- **End-to-end eval smoke + docs.** A full eval run through the new engine; document the engine layer (binding, snapshot API, tune knobs with ranges/timing, level format) and record the open-question resolutions.

## Capabilities

### New Capabilities
<!-- none new; this change advances capabilities introduced by custom-nethack-engine -->

### Modified Capabilities
- `nethack-engine`: the fork `_engine` binding becomes the sole backend; `nle` removed; `EngineEnv` canonical; adds snapshot-based divergent `branch(n, reseed)` exploration.
- `level-customization`: adds the generate/save/load level-file-blob model (`nle_save_level`/`nle_load_level`) and the MiniHack-curriculum migration (drop `minihack`); resolves the level format (OQ4 = concrete `savelev`/`getlev` blobs).
- `difficulty-tuning`: adds the remaining map-generation knobs (mob/trap/door/corridor/room_size).

> Note: `replay-viewer` is **not** modified — it renders stored NDJSON traces and never re-executes the engine. The replay change here is to `legacy/replay.py`'s `(seed,actions)` re-execution, folded into `nethack-engine` (snapshot/branch).

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
- Lines: 1-50
- SHA256: 191c4a17a4f7281d46b076d4cc4a14d322cc8b967e99a4d5967ff4531f76d303

```md
# Tasks — level-replay

> Finishes the `custom-nethack-engine` migration. Absorbs that change's remaining open
> tasks (§3.5, §5, §6, §7.5–7.6, §2.3–2.4, §8, Pillar 2 knobs).

## 0. De-risking spikes (gate their workstreams)
- [ ] 0.1 **Spike — standalone level load:** save a floor at dlvl N, end, fresh `nle_start`, `load_level`, assert obs grid matches the saved floor and play proceeds (dungeon-context fields bind correctly)
- [ ] 0.2 **Spike — mid-episode reseed:** restore one snapshot with two different reseeds, step the same action, assert outcomes can diverge over K steps while `reseed=False` stays identical; fall back to display-RNG-only or control-only if core reseed is unsafe

## 1. Fork C API (submodule → fork branch + PR)
- [ ] 1.1 `nle_save_level(ctx, buf, len) -> n` (built on `savelev`) and `nle_load_level(ctx, bytes)` (`getlev`) — concrete level-file blobs; load applies before play
- [ ] 1.2 Wire remaining Pillar 2 generation knobs to their `mklev`/spawn read-sites: `mob_spawn`, `trap_density`, `locked_door`, `corridor_connectivity`, `room_size`
- [ ] 1.3 Reseed-after-restore support for divergent branching (per Spike 0.2 outcome)
- [ ] 1.4 Open the fork PR; after merge, bump the `third_party/NetHack` submodule pointer in the harness

## 2. Binding surface (`_engine` / `EngineEnv`)
- [ ] 2.1 Expose `save_level(path)` / `load_level(path)` on `RawEngine` and `EngineEnv` against a floor-library dir (closes custom-nethack-engine §4.4 partial)
- [ ] 2.2 Expose the new generation knobs through the tune surface; assert they round-trip
- [ ] 2.3 `EngineEnv.branch(n, reseed=True)` — N divergent continuations from a snapshot
- [ ] 2.4 Tests: save→load round-trip (loaded floor == saved), generate-N-floors smoke, new knobs settable + safe

## 3. Make `EngineEnv` canonical (harness integration)
- [ ] 3.1 `NetHackCoreEnv.seed/reset/step` delegate to `EngineEnv`; build `CoreObservation` from binding buffers
- [ ] 3.2 Verify `observations.py` `shape()` + `StructuredObservation` field/type parity vs the pre-cutover shape (parity test)
- [ ] 3.3 Update `skills.py` action-index mapping + `last_observation`/`_observation_keys` reads to the binding
- [ ] 3.4 Snapshot/restore + tune surface available on the canonical env (delegated from `EngineEnv`)

## 4. Snapshot + explore (replace `legacy/replay.py` re-execution)
- [ ] 4.1 Swap `legacy/replay.py`'s `(seed,actions)` re-execution to snapshot/restore; keep old recordings viewer-readable (no migration)
- [ ] 4.2 Test: `branch(n, reseed=True)` shows outcome variance across branches; `reseed=False` identical; plain `restore` byte-exact
- [ ] 4.3 Update `tests/test_replay.py` + `record_demo.py` to the snapshot mechanism

## 5. Level customization + curriculum migration
- [ ] 5.1 Format = concrete `savelev`/`getlev` blobs (OQ4); curriculum assets under `nethack_core/levels/` — documented in the design doc
- [ ] 5.2 Compile the 3 static des tiers once (des → `lev_comp` → instantiate → `save_level`) to level blobs; native tiers stay native generation
- [ ] 5.3 Behavioral-smoke parity: each migrated tier loads, shows the specified features (downstair, monsters/room), and a short rollout runs — verified with `minihack` uninstalled (no byte-match)
- [ ] 5.4 Remove the `minihack` git dependency from `pyproject.toml` + lockfiles

## 6. The nle cutover
- [ ] 6.1 Delete the `import nle` code path from `nethack_core` (env.py / __init__.py)
- [ ] 6.2 Remove `nle>=1.3.0` from every `pyproject.toml` + lockfile; `uv sync` resolves clean without it
- [ ] 6.3 Repo-wide acceptance check: `grep -rn "import nle\|from nle\|minihack"` is clean outside archived/legacy docs
- [ ] 6.4 Update `Dockerfile.prime` to build the submodule (`build_engine.sh`) instead of installing the nle wheel
- [ ] 6.5 Bundle/vendor a tileset for `image_render.py` (MiniHack's `GlyphMapper` source is gone); `NETHACK_TILESET` override already exists

## 7. Verify + docs
- [ ] 7.1 GATE A golden-trace parity + determinism still green after the cutover
- [ ] 7.2 Full eval smoke run end-to-end through the new engine
- [ ] 7.3 Document the engine layer: binding, snapshot API, tune knobs (ranges + timing), level format; `--recurse-submodules` clone + build steps in README/dev docs
- [ ] 7.4 Record open-question resolutions (OQ4 + final API signatures); mark the absorbed `custom-nethack-engine` tasks as superseded-by `level-replay`
```

## openspec/changes/level-replay/specs/difficulty-tuning/spec.md

- Source: openspec/changes/level-replay/specs/difficulty-tuning/spec.md
- Lines: 1-14
- SHA256: 19ca7ed7a352146785a726110e513e50e8c8d8f02720ded90272e4e27a416500

```md
# difficulty-tuning (delta — level-replay)

## ADDED Requirements

### Requirement: Remaining map-generation knobs
The `nle_tune` catalog SHALL include the remaining generation knobs `mob_spawn`, `trap_density`, `locked_door`, `corridor_connectivity`, and `room_size`, each wired to its `mklev`/spawn read-site and applied at level generation (tune-at-start), consistent with the existing `room_density` knob.

#### Scenario: New knobs are settable and safe
- **WHEN** each new generation knob is set (at start) across its range and a floor is generated
- **THEN** the knob round-trips through the tune surface and the floor still generates without crashing

#### Scenario: Visible-effect knobs change the floor
- **WHEN** a knob with an observable effect (e.g. `room_size`) is set away from its default and a fixed seed is generated
- **THEN** the generated floor differs from the default-knob floor in the expected direction (knobs whose effects are off-screen are covered by settability + smoke only)
```

## openspec/changes/level-replay/specs/level-customization/spec.md

- Source: openspec/changes/level-replay/specs/level-customization/spec.md
- Lines: 1-21
- SHA256: 46561d6d2350a099d5628d534c8f1ae11be30f3b778a4cfb8688f66d608e1291

```md
# level-customization (delta — level-replay)

## ADDED Requirements

### Requirement: Generate, save, and load floor blobs
The engine SHALL let a caller generate floors natively (seed + generation knobs), save the current floor to a portable level-file blob, and start a session on a saved floor. The blob format SHALL be NetHack's concrete `savelev`/`getlev` level file. The binding SHALL expose `nle_save_level`/`nle_load_level`; `EngineEnv` SHALL expose `save_level(path)`/`load_level(path)` against a floor-library directory.

#### Scenario: Save/load round-trip
- **WHEN** a floor is generated, saved via `save_level(path)`, then loaded into a fresh session via `load_level(path)`
- **THEN** the loaded floor's observation grid matches the saved floor and play proceeds normally

#### Scenario: Generate an arbitrary number of floors
- **WHEN** floors are generated across varying seeds/knobs and saved
- **THEN** distinct floor blobs are produced and each reloads to its saved layout

### Requirement: Curriculum runs without MiniHack
The curriculum tiers SHALL run with `minihack` removed. The static des tiers (`empty_room`, `solo_combat`, `multi_combat`) SHALL be compiled once to level-file blobs (des → `lev_comp` → instantiate → save) and loaded via `load_level`; the native-generation tiers SHALL use the engine's generation directly.

#### Scenario: Migrated tiers load and play (behavioral smoke)
- **WHEN** each migrated curriculum tier is loaded
- **THEN** it presents the specified features (a downstair, the specified monsters/room) and a short rollout runs to completion — verified without `minihack` installed
```

## openspec/changes/level-replay/specs/nethack-engine/spec.md

- Source: openspec/changes/level-replay/specs/nethack-engine/spec.md
- Lines: 1-27
- SHA256: 9e0c6301cd3431d3c83627053a254239a81a88bc13677493fcdaca1dfe062f42

```md
# nethack-engine (delta — level-replay)

## MODIFIED Requirements

### Requirement: The fork engine is the sole backend
The harness SHALL drive NetHack exclusively through the fork `_engine` binding; the `nle` PyPI package SHALL NOT be imported or depended upon. `NetHackCoreEnv.seed/reset/step` SHALL delegate to `EngineEnv`, building `CoreObservation` from the binding buffers, and `observations.py` `shape()` + `StructuredObservation` field/type surface SHALL be unchanged for consumers.

#### Scenario: No nle dependency remains
- **WHEN** the repo is searched for `import nle` / `from nle` / `minihack`
- **THEN** there are no live references outside archived/legacy docs, and `uv sync` resolves with `nle` and `minihack` removed from every `pyproject.toml`/lockfile

#### Scenario: Observation parity across the cutover
- **WHEN** an episode is stepped through the post-cutover `NetHackCoreEnv`
- **THEN** the `StructuredObservation` field names/types/shapes match the pre-cutover contract, and GATE A golden-trace parity + determinism suites stay green

## ADDED Requirements

### Requirement: Snapshot-based divergent exploration
`EngineEnv` SHALL expose `branch(n, reseed=True)` that produces `n` continuations from the current state via snapshot/restore. With `reseed=True` the engine SHALL reseed the RNG after restore so random-chance events (spawns, search, doors) can diverge across branches; with `reseed=False` the branches SHALL be identical to a plain restore. Plain `snapshot()`/`restore()` SHALL remain byte-exact.

#### Scenario: Reseeded branches diverge
- **WHEN** `branch(n, reseed=True)` is called and each continuation steps the same action sequence
- **THEN** the continuations can yield different outcomes (observable variance over K steps), while `reseed=False` continuations are identical

#### Scenario: Plain restore stays exact
- **WHEN** a snapshot is restored without reseeding and stepped
- **THEN** the result is byte-identical to the original timeline (existing snapshot guarantee preserved)
```

