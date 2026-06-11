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
