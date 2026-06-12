# Comet Design Handoff

- Change: custom-nethack-engine
- Phase: design
- Mode: compact
- Context hash: 7a10e1b90c6546535f96740d53383448dc84eb9e30dedb5bc40e1d06afb1c120

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/custom-nethack-engine/proposal.md

- Source: openspec/changes/custom-nethack-engine/proposal.md
- Lines: 1-33
- SHA256: e81f02716a7c6211f956ce11ce2904bf2e28f386e65b49e611f2be2197d9dc4f

```md
## Why

The harness currently drives NetHack through the `nle>=1.3.0` PyPI package, which gives us no control over the game internals: we cannot snapshot/restore game state in O(1), we cannot tune difficulty, and we cannot customize levels beyond the MiniHack des-file path. We now have a custom struct-based NetHack fork (https://github.com/liujonathan24/NetHack) that moves all process-global game state into a per-env `nle_ctx_t` struct (~75 KB, reached via initial-exec TLS `current_nle_ctx`) and builds to `libnethack.so`. Because the whole game lives in one struct, we can finally get cheap state cloning (replay), expose tunable difficulty knobs, and load custom levels — capabilities the eval/research roadmap needs. The fork is developed by the same user, so the required engine-side C entry points are in scope.

## What Changes

- **BREAKING**: Remove the `nle>=1.3.0` PyPI dependency and drive the game through the fork's `libnethack.so` instead. Full cutover — no `nle` fallback retained.
- Add the fork (`liujonathan24/NetHack`) as a **git submodule** with a documented build path producing `libnethack.so` + game data; wire it into the Python build/install and `Dockerfile.prime`.
- Add a **standalone ctypes/cffi binding** in this repo (a new `_engine` module). No PufferLib or NLE-Python dependency. The binding fills raw observation buffers; the existing `observations.py` `shape()` pipeline is reused by constructing `CoreObservation` from those buffers instead of from an NLE obs dict.
- Add **O(1) struct snapshot/restore**: `snapshot() -> bytes` and `restore(bytes)` over `nle_ctx_t`, replacing/superseding the O(n) action-replay in `legacy/replay.py`.
- Add **difficulty tuning**: a new `nle_tune_t` knob sub-struct read at engine decision sites, exposed to Python as runtime-settable knobs (`mob_spawn_rate`, `dmg_to_player_scale`, `player_hp_scale`, `vision_radius`, `fog_of_war` on/off, `floor_subset`/`start_dlvl`, `locked_door_rate`, `luck_override`, per-attribute overrides, …). Designed to be extensible: a new knob = one struct field + one engine read site.
- Add **level customization**: an engine entry point to load a custom level/scenario (des-file or struct-prep), so curriculum scenarios no longer depend on the separate MiniHack package.
- Define the **new fork-side C API**: `nle_get_obs`, `nle_set_seed` (deterministic, `reseed=false`), `nle_snapshot`/`nle_restore`, `nle_get_tune`/`nle_set_tune`, `nle_load_level` (atop the existing `nle_start`/`nle_step`/`nle_end`). These land in the submodule but are specified here.
- Migrate harness touch points: `NetHackCoreEnv` seed/reset/step, `observations.py` `shape()`, `skills.py` action-index mapping and `last_observation` reads, curriculum tiers' MiniHack usage, `pyproject.toml`, `Dockerfile.prime`.

## Capabilities

### New Capabilities
- `nethack-engine`: How the harness obtains, builds, and binds the custom NetHack engine (submodule, `libnethack.so`, ctypes/cffi binding, observation buffer extraction, deterministic seeding, action stepping) — the contract that replaces the `nle` dependency.
- `state-snapshot`: O(1) struct snapshot/restore of game state for replay and branching, including how snapshot completeness is guaranteed (in-memory ctx + any on-disk level state).
- `difficulty-tuning`: The `nle_tune_t` knob block and its Python surface — which knobs exist, their semantics/ranges, when they take effect (reset-time vs live), and how new knobs are added.
- `level-customization`: Loading custom levels/scenarios into the engine, and how curriculum tiers move off MiniHack onto this path.

### Modified Capabilities
<!-- No existing OpenSpec specs in openspec/specs/ yet; this is the first formal capability set for the engine layer. -->

## Impact

- **Dependencies**: Removes `nle>=1.3.0`; removes/loosens the MiniHack git dependency once level-customization replaces it. Adds a git submodule + native build toolchain (cmake/bison/flex/libbz2) already present in `Dockerfile.prime`.
- **Code**: `environments/nethack/nethack_core/env.py` (`NetHackCoreEnv` seed/reset/step), `environments/nethack/nethack_core/observations.py` (`shape()` source), `environments/nethack/nethack_harness/tools/skills.py` (action-index mapping, `last_observation`/`_observation_keys` reads), `legacy/replay.py` (action-replay → struct-snapshot), `environments/nethack/nethack_harness/curriculum/curriculum.py` (MiniHack tiers), `pyproject.toml` files, `Dockerfile.prime`.
- **Engine (submodule)**: New C API surface and `nle_tune_t` struct in `liujonathan24/NetHack`; tracked as submodule work but specified by this change.
- **Determinism/replay**: Replay model changes from action-sequence replay to struct snapshot/restore. Leading risk: `nle_ctx_t` (~75 KB) is smaller than a full multi-level dungeon (NetHack swaps inactive levels to disk), so a true clone may require capturing ctx + on-disk level files — this gates the snapshot/replay API shape and is the first spike.
- **Platforms**: Native build moves from pip-installed `nle` wheel to a locally built `.so`; CI/Docker and local dev install paths change.
```

## openspec/changes/custom-nethack-engine/design.md

- Source: openspec/changes/custom-nethack-engine/design.md
- Lines: 1-74
- SHA256: 21469ac78b6d0e8b39174bb822837e7f7f4644b83b544bc8a0419e42653b1c8d

```md
## Context

Today the harness drives NetHack via `nle>=1.3.0` (PyPI), wrapped by `NetHackCoreEnv` (`environments/nethack/nethack_core/env.py`) over `gym.make`. It consumes NLE's observation dict (`tty_chars`, `tty_colors`, `tty_cursor`, `glyphs`, `chars`, `colors`, `message`, `blstats`, `inv_strs`, `inv_letters`, `inv_glyphs`), steps integer actions, and seeds deterministically via `nethack.set_initial_seeds(core, disp, reseed=False)`. Replay is O(n) action-replay (`legacy/replay.py`). Curriculum difficulty tiers piggyback on MiniHack des-files.

The custom fork (`liujonathan24/NetHack`, a fork of NLE 0.9.0 / NetHack 3.6.6) moves all process-global state into a per-env `nle_ctx_t` struct (~75 KB) reached via initial-exec TLS (`current_nle_ctx`), and builds to `libnethack.so`. Its C API (`nle_start`/`nle_step`/`nle_end`) is unchanged; everything the harness needs beyond that is greenfield. The fork is currently consumed only by PufferLib's native C vecenv (cloned by PufferLib's `build.sh`); there is no standalone Python binding and no docs for the C API beyond the README.

The user owns the fork, so engine-side C additions are in scope. The harness and the objective-driven plan live in this repo; engine changes are tracked as submodule work.

## Goals / Non-Goals

**Goals:**
- Full cutover: the harness builds and drives the fork's `libnethack.so` with **no** `nle` PyPI dependency and **no** PufferLib dependency in the eval install path.
- A standalone ctypes/cffi binding in this repo that fills the same observation buffers the harness already decodes, so `observations.py` `shape()` and downstream tooling are reused unchanged.
- O(1) struct snapshot/restore as the new replay/branching primitive.
- A `nle_tune_t` difficulty-knob block exposed to Python, runtime-settable, and trivially extensible.
- Level customization that lets curriculum scenarios drop the separate MiniHack dependency.
- Determinism preserved: deterministic seeding (`reseed=false`) and reproducible rollouts.

**Non-Goals:**
- Keeping any `nle` fallback path (explicitly cut over).
- Re-deriving NLE's RL observation wrappers/reward shaping — the harness already shapes its own observations and rewards.
- A general-purpose NetHack save/restore compatible with vanilla NetHack `dosave`/`dorecover`; we want struct snapshot, not on-disk savefile parity.
- Cross-machine / cross-build snapshot portability (struct layout is build-specific; snapshots are valid within a build).
- Multi-instance-per-process concurrency in the harness (the fork supports it; the eval harness runs one game per env). The binding should not preclude it, but it is not a goal.

## Decisions

### D1: Standalone ctypes/cffi binding, not PufferLib reuse or NLE-Python graft
The harness needs the rich NLE-style observation buffers and direct struct access for snapshots/knobs. PufferLib exposes RL-flat observations and pulls a heavy dependency; grafting onto NLE 1.3.0's pybind layer means reconciling the fork's 0.9.0/TLS C lineage with 1.3.0 glue. A thin ctypes/cffi `_engine` module that calls the fork's C API directly and writes into pre-allocated numpy buffers is the smallest, most controllable surface, and gives native access to `nle_ctx_t` for snapshot/tune. *Alternatives considered:* reuse PufferLib binding (rejected: obs shape + dependency weight); graft into NLE 1.3.0 pybind (rejected: most fragile C integration).

### D2: Reuse `CoreObservation` / `observations.py`, swap only the source
`NetHackCoreEnv.step/reset` will build `CoreObservation` from buffers the binding fills, instead of from an NLE gym obs dict. `shape()` and all structured-observation consumers stay byte-compatible. This isolates the migration to the env wrapper + binding and keeps the prompt/observation contract stable. *Alternative:* new observation type (rejected: needless churn across skills/tools/replay viewer).

### D3: Snapshot = `memcpy(nle_ctx_t)`, completeness verified by spike first
Snapshot/restore is `nle_snapshot(ctx)->bytes` / `nle_restore(ctx, bytes)`. The open risk (R1) is whether the ~75 KB ctx is a *complete* clone given NetHack swaps inactive levels to disk. The change **leads with a spike**: snapshot at dlvl 1, descend, restore, and assert state parity (incl. previously-visited levels). The spike outcome picks one of: (a) ctx is complete → pure memcpy; (b) bundle ctx + on-disk level files into the snapshot blob; (c) force levels in-memory in the fork. The Python API (`snapshot()->bytes`, `restore(bytes)`) is identical regardless; only the blob's internals differ. *Alternative:* keep action-replay (rejected: O(n), the whole point of the fork is O(1)).

### D4: Difficulty as a `nle_tune_t` sub-struct of `nle_ctx_t`, single get/set surface
All knobs live in one struct read at engine decision sites (makemon spawn, damage calc, vision radius, mklev door/level gen, attribute init, luck). Python sees `tune.get() -> dict` / `tune.set(**knobs)` over the whole block, so adding a knob is one C field + one read site + nothing in the binding. Each knob's spec must state **when it takes effect** (reset-time vs live mid-game) since some (e.g. `start_dlvl`, `floor_subset`) only make sense at generation time while others (`dmg_to_player_scale`, `fog_of_war`) can be live. *Alternative:* per-knob C functions (rejected: O(knobs) plumbing, poor extensibility).

### D5: Level customization via an engine load entry point; curriculum migrates off MiniHack
`nle_load_level` loads a custom level/scenario (des-file or a struct-prep produced by a difficulty preset). Curriculum tiers that currently pass MiniHack `des_file` move onto this path; the MiniHack git dependency is removed once parity is reached. A difficulty/level preset can also be expressed as a saved snapshot (D3), unifying "custom level" and "difficulty preset" under the snapshot primitive where convenient. *Alternative:* keep MiniHack (rejected: contradicts full-cutover and adds an NLE-0.9.0-pinned dependency).

### D6: Submodule + native build wired into install and Docker
Add the fork as a git submodule (pinned commit). A build step runs `make -C src/build nethack -j` to produce `libnethack.so` + data, located by the binding at runtime via an env var / packaged path. `Dockerfile.prime` already has the toolchain (cmake/bison/flex/libbz2); the install path swaps the `nle` wheel build for the submodule build. *Alternative:* vendor prebuilt `.so` (rejected: non-portable, hides build, blocks fork iteration).

## Risks / Trade-offs

- **R1 — Snapshot completeness (gating):** `nle_ctx_t` (~75 KB) may not capture disk-swapped levels → restore loses visited levels. *Mitigation:* lead with the snapshot-parity spike (D3); pick blob strategy from its result before finalizing the replay API.
- **R2 — Observation buffer parity:** subtle differences in fork buffer layout/encoding (glyph ranges, message null-termination, blstats indices) vs NLE 1.3.0 → silently wrong observations. *Mitigation:* golden-trace parity test — same seed/actions through old `nle` path (recorded) vs new binding, assert byte-identical `tty_chars`/`blstats`/`message` for N steps before deleting the `nle` path.
- **R3 — Action encoding drift:** the fork's action table vs the indices `skills.py` emits. *Mitigation:* derive the action mapping from the engine's action list at binding init; assert the compass/misc enums match expected glyph outcomes in tests.
- **R4 — Seeding semantics:** the fork is NLE 0.9.0 lineage; `set_initial_seeds` semantics/timing may differ. *Mitigation:* define `nle_set_seed(core, disp)` to seed before `nle_start`, `reseed=false`; verify two same-seed rollouts are step-identical.
- **R5 — Build/portability friction:** locally built `.so` instead of a wheel complicates dev setup and CI. *Mitigation:* document the submodule build; cache the build in Docker; fail fast with a clear message if `libnethack.so` is missing.
- **R6 — Snapshot portability:** struct snapshots are build-specific (layout depends on compiler/flags). *Mitigation:* tag snapshots with a build/struct-version id; refuse to restore across mismatched ids.
- **R7 — Big-bang blast radius:** one end-to-end change touches binding, obs, replay, curriculum, build. *Mitigation:* internal ordering — engine+binding+parity gate first, then snapshot, then tune, then level/curriculum — each with its own tests, even though it ships as one change.

## Migration Plan

1. Add submodule + build; produce `libnethack.so`; binding can `nle_start/step/end` a no-op rollout.
2. Implement `nle_get_obs` + binding buffer fill; pass R2 golden-trace parity vs recorded `nle` traces.
3. Switch `NetHackCoreEnv` to the binding; run existing harness tests; remove `nle` from `pyproject.toml`.
4. Snapshot spike (R1) → implement `nle_snapshot`/`nle_restore` + Python `snapshot()/restore()`; replace `legacy/replay.py` internals.
5. Implement `nle_tune_t` + `nle_get/set_tune` + Python `tune` surface; per-knob tests.
6. Implement `nle_load_level`; migrate curriculum tiers off MiniHack; drop MiniHack dep.
7. Update `Dockerfile.prime` + docs; full eval smoke run.

**Rollback:** full cutover means rollback = revert the change / pin back to `nle`. The golden-trace gate (step 2–3) is the point of no return; do not delete the `nle` path until parity passes.

## Open Questions

- **OQ1:** Does `nle_ctx_t` already include disk-swapped level state, or must the snapshot blob bundle on-disk level files? (Resolved by the R1 spike — gates the API blob format.)
- **OQ2:** Which knobs are reset-time-only vs live-settable? Needs enumeration in the `difficulty-tuning` spec.
- **OQ3:** Does the fork's NLE-0.9.0 action table match the action indices the harness emits 1:1, or is a remap table needed?
- **OQ4:** Level customization format — reuse NetHack `.des` files (parser already in the engine) or a new struct-prep/preset format? Affects how curriculum tiers are re-authored.
- **OQ5:** Does the binding need to support more than one live `nle_ctx_t` per process for any harness use (e.g. branching search holding multiple restored states simultaneously), or is one-active-ctx + snapshot blobs sufficient?
```

## openspec/changes/custom-nethack-engine/tasks.md

- Source: openspec/changes/custom-nethack-engine/tasks.md
- Lines: 1-56
- SHA256: e6aeb5505fc590c76bedb4eafaa41c30a17a61e37fb00e7735d3550d16d9f275

```md
## 1. Snapshot-completeness spike (gating)

- [ ] 1.1 Add the fork as a git submodule (pinned commit) under e.g. `third_party/NetHack`; build `libnethack.so` locally and confirm the build command from the README works
- [ ] 1.2 Write a throwaway C/ctypes probe that calls `nle_start`/`nle_step`/`nle_end`, descends a few levels, and memcpys `nle_ctx_t`
- [ ] 1.3 Determine whether `nle_ctx_t` (~75 KB) captures disk-swapped level state; document the result (resolves OQ1/R1)
- [ ] 1.4 Decide the snapshot blob strategy: pure ctx memcpy | ctx + bundled on-disk level files | force in-memory levels; record the decision in design.md

## 2. Engine submodule + build wiring

- [ ] 2.1 Define where `libnethack.so` + game data live after build and how the binding locates them (env var / packaged path)
- [ ] 2.2 Wire the submodule build into the Python install path; fail fast with a clear message when `libnethack.so` is missing
- [ ] 2.3 Update `Dockerfile.prime` to build the submodule instead of installing the `nle` wheel (toolchain already present)
- [ ] 2.4 Document the `--recurse-submodules` clone + build steps in the README/dev docs

## 3. Fork-side C API (submodule work, specified here)

- [ ] 3.1 `nle_get_obs(ctx, buffers...)` — fill tty_chars/colors/cursor, glyphs, chars, colors, message, blstats, inv_strs/letters/glyphs
- [ ] 3.2 `nle_set_seed(core, disp)` — deterministic, applied before start, `reseed=false`
- [ ] 3.3 `nle_snapshot(ctx) -> bytes` / `nle_restore(ctx, bytes)` per the strategy chosen in 1.4, with a build/struct-version tag
- [ ] 3.4 `nle_tune_t` sub-struct in `nle_ctx_t` + `nle_get_tune`/`nle_set_tune`; wire each knob to its engine read site (makemon, damage, vision/fog, mklev doors/levels, attrs, luck)
- [ ] 3.5 `nle_load_level(ctx, ...)` — load a custom level/scenario description

## 4. Standalone ctypes/cffi binding (`_engine`)

- [ ] 4.1 Create the `_engine` module: load `libnethack.so`, declare argtypes/restypes, allocate observation buffers
- [ ] 4.2 Implement start/step/end + `nle_get_obs` fill into numpy buffers
- [ ] 4.3 Derive the action mapping from the engine's action table; assert compass/misc enums (resolves OQ3/R3)
- [ ] 4.4 Expose seed, snapshot/restore, tune get/set, and load_level through the binding

## 5. Harness integration

- [ ] 5.1 Rewrite `NetHackCoreEnv.seed/reset/step` to drive `_engine`; build `CoreObservation` from binding buffers
- [ ] 5.2 Keep `observations.py` `shape()` and consumers unchanged; verify `StructuredObservation` field/type parity
- [ ] 5.3 Update `skills.py` action-index mapping and `last_observation`/`_observation_keys` reads to the new binding
- [ ] 5.4 Replace `legacy/replay.py` action-replay internals with snapshot/restore; preserve any trajectory surface the replay viewer consumes
- [ ] 5.5 Add `snapshot()`/`restore()` and a `tune` surface (`tune.get()`/`tune.set(**knobs)`) on the env

## 6. Level customization + curriculum migration

- [ ] 6.1 Re-express curriculum tiers' MiniHack `des_file`s via `nle_load_level` (or snapshot presets)
- [ ] 6.2 Remove the MiniHack git dependency and confirm tiers run without it
- [ ] 6.3 Decide and document the preset/level format (resolves OQ4)

## 7. Parity, determinism, and cutover gate

- [ ] 7.1 Golden-trace parity test: record an `nle` trace, replay same seed/actions through `_engine`, assert byte-identical tty_chars/blstats/message for N steps (R2)
- [ ] 7.2 Determinism test: two same-seed rollouts are step-identical (R4)
- [ ] 7.3 Snapshot round-trip + multi-level + version-guard tests (spec: state-snapshot)
- [ ] 7.4 Per-knob effect tests incl. reset-time vs live timing (spec: difficulty-tuning)
- [ ] 7.5 Only after 7.1–7.2 pass: remove `nle>=1.3.0` from all `pyproject.toml`/lockfiles and delete the `nle` code path
- [ ] 7.6 Full eval smoke run end-to-end through the new engine

## 8. Docs

- [ ] 8.1 Document the new engine layer: binding, snapshot API, tune knobs (with timing + ranges), level customization
- [ ] 8.2 Record open-question resolutions (OQ1–OQ5) and final API signatures
```

## openspec/changes/custom-nethack-engine/specs/difficulty-tuning/spec.md

- Source: openspec/changes/custom-nethack-engine/specs/difficulty-tuning/spec.md
- Lines: 1-92
- SHA256: 463f27a9774300b35c4bd892851761122c040bb3d78bf18a71cc08f5a1220371

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: Difficulty knob block
The engine SHALL hold a `nle_tune_t` knob sub-struct within `nle_ctx_t`, read at the relevant decision sites, and SHALL expose `nle_get_tune`/`nle_set_tune`. The harness SHALL surface it as `tune.get() -> dict` and `tune.set(**knobs)`. The v1 knob catalog below is canonical; each knob is tagged with its layer, timing (R = reset/generation-time, L = live per-step), type, default, and engine read-site.

**Layer 0 — Start state** (timing R unless noted)

| Knob | Type | Default | Read-site |
| --- | --- | --- | --- |
| `role` / `race` / `gender` / `alignment` | enum | random | `u_init.c` |
| `start_dlvl` | int | 1 | start `goto_level` / `u.uz` |
| `starting_inventory` | list | role default | `nle_settings.wizkit` / `u_init.c` |
| `attr_overrides` (STR..CHA) | int? | none | `attrib.c` / `u.acurr` |
| `luck_override` (L) | int | 0 | `u.uluck` |
| `starting_gold` | int | role default | `u_init.c` |

**Layer 1 — Topology** (timing R)

| Knob | Type | Default | Read-site |
| --- | --- | --- | --- |
| `max_floors` | int | 25±5 | `init_dungeons` / `dungeon.def` clamp |
| `enabled_branches` | set | all | `init_dungeons` / `add_branch` |
| `floor_subset` | list[int] | all | dungeon topology |

**Layer 2 — Parametric generation** (timing R, applied per level in `mklev`)

| Knob | Type | Default | Read-site |
| --- | --- | --- | --- |
| `room_density` | float | 1.0 | `makerooms` (mklev.c) |
| `room_size_scale` | float | 1.0 | `do_room_or_subroom` |
| `corridor_connectivity` | float | 1.0 | `makecorridors` (mklev.c) |
| `locked_door_rate` | float | vanilla | `dosdoor` `D_LOCKED` branch |
| `door_trap_rate` | float | vanilla | `dosdoor` `D_TRAPPED` |
| `secret_door_rate` | float | vanilla | `dosdoor` SDOOR |
| `mob_spawn_scale` | float | 1.0 | `makelevel` populate / `makemon` |
| `object_spawn_scale` | float | 1.0 | `mkobj` density |
| `trap_density` | float | 1.0 | `mktrap` |

**Layer 3 — Engine mechanics** (timing L)

| Knob | Type | Default | Read-site |
| --- | --- | --- | --- |
| `dmg_to_player_scale` | float | 1.0 | `mhitu.c` |
| `dmg_by_player_scale` | float | 1.0 | `uhitm.c` |
| `player_hp_scale` | float | 1.0 | `u.uhpmax` + regen |
| `hp_regen_scale` | float | 1.0 | regen (`allmain.c`) |
| `vision_radius` | int | vanilla | `vision.c` |
| `fog_of_war` | bool | true | vision/display |
| `reveal_map` | bool | false | display (mark seen) |
| `hunger_rate_scale` | float | 1.0 | `eat.c` / `gethungry` |
| `ongoing_spawn_scale` | float | 1.0 | periodic `makemon` |
| `monster_difficulty_scale` | float | 1.0 | `level_difficulty()` (dungeon.c) |
| `monster_speed_scale` | float | 1.0 | `mon.c` movement |
| `xp_gain_scale` | float | 1.0 | experience award |

#### Scenario: Read defaults
- **WHEN** `tune.get()` is called on a fresh game with no overrides
- **THEN** it returns every catalog knob with its default value, and the defaults reproduce vanilla NetHack behavior

#### Scenario: Set a live engine knob and observe effect
- **WHEN** `tune.set(dmg_to_player_scale=0.0)` is applied and the player is attacked
- **THEN** the player takes no damage from that attack, reflected in `blstats` HP

#### Scenario: Fog of war toggle
- **WHEN** `tune.set(fog_of_war=False)` is applied
- **THEN** the observation reveals the level beyond the normal vision/lit area

#### Scenario: Parametric generation knob changes the generator
- **WHEN** `locked_door_rate` is lowered and a new game/level is generated with a fixed seed
- **THEN** the generated level contains proportionally fewer locked doors than the vanilla default at that seed

### Requirement: Knob effect timing is specified
Each knob SHALL honor its catalog timing tag. Reset/generation-time (R) knobs SHALL be applied before game/level generation; live (L) knobs SHALL take effect on the next step after being set. Setting an R knob mid-episode SHALL be accepted and applied at the next reset, and the binding SHALL signal that it is deferred rather than silently partially applied.

#### Scenario: Reset-time knob applied at generation
- **WHEN** `start_dlvl` is set before reset
- **THEN** the new game begins on that dungeon level

#### Scenario: Live knob applied mid-game
- **WHEN** `vision_radius` is changed during play
```

Full source: openspec/changes/custom-nethack-engine/specs/difficulty-tuning/spec.md

## openspec/changes/custom-nethack-engine/specs/level-customization/spec.md

- Source: openspec/changes/custom-nethack-engine/specs/level-customization/spec.md
- Lines: 1-30
- SHA256: bcafc31cbcf29d03811c6b336b348233593ea97d1d0ed3be613b4ffec4dee956

```md
## ADDED Requirements

### Requirement: Custom level loading
The engine SHALL expose `nle_load_level` to load a custom level/scenario (a NetHack `.des` description and/or a struct-prep produced from a difficulty preset), and the harness SHALL invoke it so that a rollout begins on the specified custom level.

#### Scenario: Load a custom des-file level
- **WHEN** a rollout is configured with a custom level description and reset
- **THEN** the game starts on that level with the described layout, monsters, and features

#### Scenario: Invalid level description rejected
- **WHEN** a malformed level description is supplied
- **THEN** loading fails with a clear error before the rollout starts, not mid-game

### Requirement: Curriculum tiers migrate off MiniHack
Curriculum tiers that currently depend on MiniHack `des_file`s SHALL be re-expressed through `nle_load_level` (or snapshot-based presets), and the MiniHack git dependency SHALL be removed once parity is reached.

#### Scenario: Existing tier runs without MiniHack
- **WHEN** a tier that previously required MiniHack is run after migration in an environment without MiniHack installed
- **THEN** the tier loads its level and runs to its success criterion as before

#### Scenario: MiniHack dependency removed
- **WHEN** project dependencies are inspected after curriculum migration
- **THEN** the MiniHack git dependency is absent and no tier imports it

### Requirement: Preset = snapshot equivalence
A difficulty/level preset expressed as a saved snapshot SHALL load by restoring that snapshot, and loading it MUST yield a reproducible starting state across rollouts.

#### Scenario: Preset restores identical start
- **WHEN** the same preset snapshot is loaded at the start of multiple rollouts
- **THEN** each rollout begins from a byte-identical starting observation
```

## openspec/changes/custom-nethack-engine/specs/nethack-engine/spec.md

- Source: openspec/changes/custom-nethack-engine/specs/nethack-engine/spec.md
- Lines: 1-52
- SHA256: 4f2a43c43d3aba0c500d2430bb951bee121e7ede1f39e0b2e22c0ed1493d5609

```md
## ADDED Requirements

### Requirement: Engine sourced from the fork submodule
The harness SHALL obtain the NetHack engine from the `liujonathan24/NetHack` fork pinned as a git submodule, and SHALL build it to `libnethack.so` as part of install. The `nle` PyPI package SHALL NOT be a dependency.

#### Scenario: Fresh checkout builds the engine
- **WHEN** the repo is cloned with `--recurse-submodules` and the documented build command is run
- **THEN** `libnethack.so` and the game data files are produced and discoverable by the binding

#### Scenario: nle dependency removed
- **WHEN** the project dependencies are inspected after migration
- **THEN** `nle` does not appear in any `pyproject.toml`, lockfile, or runtime import path

#### Scenario: Missing engine fails fast
- **WHEN** the binding initializes and `libnethack.so` cannot be located
- **THEN** it raises a clear error naming the expected path and the build command, rather than failing obscurely

### Requirement: Standalone ctypes/cffi binding
The harness SHALL drive the engine through a standalone `_engine` ctypes/cffi binding in this repo that calls the fork's C API (`nle_start`, `nle_step`, `nle_end`, and the new entry points). The binding SHALL NOT depend on PufferLib or any NLE Python layer.

#### Scenario: Rollout without external engine packages
- **WHEN** a rollout runs in an environment with neither `nle` nor `pufferlib` installed
- **THEN** the game starts, steps, and ends successfully through the `_engine` binding

### Requirement: Observation buffer parity
The binding SHALL fill observation buffers (`tty_chars`, `tty_colors`, `tty_cursor`, `glyphs`, `chars`, `colors`, `message`, `blstats`, `inv_strs`, `inv_letters`, `inv_glyphs`) via `nle_get_obs`, and `NetHackCoreEnv` SHALL construct `CoreObservation` from them so that `observations.py` `shape()` and downstream consumers operate unchanged.

#### Scenario: Golden-trace parity with the prior nle path
- **WHEN** the same seed and action sequence are run through a previously-recorded `nle` trace and the new binding for N steps
- **THEN** `tty_chars`, `blstats`, and `message` are byte-identical at every step

#### Scenario: Structured observation unchanged
- **WHEN** `shape()` is given a `CoreObservation` built from the binding's buffers
- **THEN** it returns a `StructuredObservation` with the same fields and types as before the migration

### Requirement: Deterministic seeding
The binding SHALL expose deterministic seeding via `nle_set_seed(core, disp)` applied before game start with `reseed=false`, preserving the harness's seed-before-reset invariant.

#### Scenario: Same seed is reproducible
- **WHEN** two rollouts use the same `(core, disp)` seed and identical actions
- **THEN** every step's observation is identical between the two rollouts

#### Scenario: Reset requires explicit seed
- **WHEN** `reset()` is called without a staged seed
- **THEN** the env raises an error rather than starting a nondeterministic game

### Requirement: Action stepping parity
The binding SHALL accept the integer actions the harness already emits and map them to the engine's action table, preserving the semantics of the existing compass/misc-direction actions.

#### Scenario: Compass move produces expected movement
- **WHEN** a known compass-direction action index is stepped from a known position
- **THEN** the player moves in the corresponding direction as reflected in the observation
```

## openspec/changes/custom-nethack-engine/specs/state-snapshot/spec.md

- Source: openspec/changes/custom-nethack-engine/specs/state-snapshot/spec.md
- Lines: 1-37
- SHA256: 3c5484e8fa6647f0a574e10aa38d1afda81d767e0989e19c4440334a8e58f487

```md
## ADDED Requirements

### Requirement: O(1) struct snapshot and restore
The engine SHALL expose `nle_snapshot(ctx) -> bytes` and `nle_restore(ctx, bytes)`, and the harness SHALL surface them as `snapshot() -> bytes` and `restore(bytes)` on the env. A snapshot SHALL capture complete game state such that restoring it yields a game indistinguishable from the snapshotted moment, and the operation SHALL be constant-time with respect to the number of steps taken.

#### Scenario: Round-trip preserves state
- **WHEN** a snapshot is taken, the game is stepped further, and the snapshot is restored
- **THEN** the post-restore observation equals the observation at snapshot time, and subsequent identical actions produce identical observations

#### Scenario: Restore is independent of step count
- **WHEN** snapshot/restore is performed after 10 steps and after 10,000 steps
- **THEN** the operation's cost does not grow with step count (no action re-execution)

### Requirement: Snapshot completeness across dungeon levels
A snapshot SHALL preserve state for all visited dungeon levels, including levels NetHack would otherwise swap to disk, so that restoring after descending and returning reproduces prior levels exactly.

#### Scenario: Multi-level round-trip (spike-gated)
- **WHEN** the player snapshots on level 1, descends to level 3, restores, and re-descends
- **THEN** levels 1–3 match their pre-restore layouts and contents

#### Scenario: Snapshot strategy documented
- **WHEN** the snapshot-completeness spike concludes
- **THEN** the chosen blob strategy (pure ctx memcpy, ctx + bundled on-disk level files, or in-memory levels) is recorded and the API contract above holds regardless of strategy

### Requirement: Snapshot build-compatibility guard
Snapshots SHALL be tagged with a build/struct-version identifier, and `restore` SHALL refuse a snapshot whose identifier does not match the running engine build.

#### Scenario: Mismatched snapshot rejected
- **WHEN** a snapshot produced by a different engine build is restored
- **THEN** `restore` raises a clear version-mismatch error instead of corrupting state

### Requirement: Replay supersedes action-replay
The struct-snapshot mechanism SHALL replace the O(n) action-replay internals in `legacy/replay.py` as the primary replay/branching primitive, while preserving any trajectory-recording surface still consumed by tooling (e.g. the replay viewer).

#### Scenario: Branching via snapshots
- **WHEN** a caller snapshots a state and explores two different action sequences from it by restoring between them
- **THEN** each branch starts from the identical snapshotted state without replaying actions from episode start
```

