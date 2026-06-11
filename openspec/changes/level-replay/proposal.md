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
