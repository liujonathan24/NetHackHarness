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
