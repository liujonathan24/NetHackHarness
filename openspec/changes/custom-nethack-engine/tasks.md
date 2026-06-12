# Tasks — custom-nethack-engine

> SUPERSEDED: the remaining open tasks (nle cutover §5/§7.5, level loading §3.5/§6, gen knobs, Docker/docs §2.3-2.4/§8) were completed under the `level-replay` change (branch level-replay, 2026-06-11). This change can be archived.

> **Status reconciled 2026-06-11** against the actual branch (`custom-nethack-engine`).
> Boxes were previously all-unchecked despite the foundation being built; this reflects real state.
>
> **Done:** the engine foundation — submodule + build, fork C API (obs, seed, snapshot/restore,
> `nle_tune_t` knobs), the standalone `_engine` binding + `EngineEnv`, GATE A golden-trace parity
> (structured buffers byte-perfect; tty/message accepted as "binding-native"), GATE B multilevel
> snapshot, determinism/snapshot/knob test suites.
>
> **NOT done — headline remaining = the cutover.** The harness still `import nle` (`env.py:25`);
> `nle>=1.3.0` + `minihack` are still hard deps. `NetHackCoreEnv` was NOT rewritten — instead a
> parallel `EngineEnv` was built. Remaining work = make `EngineEnv` the canonical env, swap
> `skills.py`/`legacy/replay.py`, remove nle, migrate the MiniHack curriculum off `nle_load_level`
> (not yet implemented), Docker/docs.
>
> **Delivered outside this checklist:** difficulty-knob catalog (12 knobs, §3.4); the web console
> (separate Comet change, archived `2026-06-11-web-console`); map-generation control "Pillar 2"
> (`room_density` live; mob/trap/door/corridor/room_size still pending).

## 1. Snapshot-completeness spike (gating)

- [x] 1.1 Add the fork as a git submodule (pinned commit) under e.g. `third_party/NetHack`; build `libnethack.so` locally and confirm the build command from the README works
- [x] 1.2 Write a throwaway C/ctypes probe that calls `nle_start`/`nle_step`/`nle_end`, descends a few levels, and memcpys `nle_ctx_t`
- [x] 1.3 Determine whether `nle_ctx_t` (~75 KB) captures disk-swapped level state; document the result (resolves OQ1/R1)
- [x] 1.4 Decide the snapshot blob strategy: pure ctx memcpy | ctx + bundled on-disk level files | force in-memory levels; record the decision in design.md — chose ctx+arena memcpy + bundled on-disk level files (see `test_snapshot_multilevel.py`)

## 2. Engine submodule + build wiring

- [x] 2.1 Define where `libnethack.so` + game data live after build and how the binding locates them (env var / packaged path) — `_engine.py` locator, `NLE_LIB_PATH` authoritative, walks up to `third_party/NetHack/src/build`
- [x] 2.2 Wire the submodule build into the Python install path; fail fast with a clear message when `libnethack.so` is missing — `EngineNotBuilt(RuntimeError)`
- [ ] 2.3 Update `Dockerfile.prime` to build the submodule instead of installing the `nle` wheel (toolchain already present) — **OPEN: still builds the nle wheel** (blocked by §7.5 cutover)
- [ ] 2.4 Document the `--recurse-submodules` clone + build steps in the README/dev docs — **OPEN** (see §8)

## 3. Fork-side C API (submodule work, specified here)

- [x] 3.1 `nle_get_obs(ctx, buffers...)` — fill tty_chars/colors/cursor, glyphs, chars, colors, message, blstats, inv_strs/letters/glyphs
- [x] 3.2 `nle_set_seed(core, disp)` — deterministic, applied before start, `reseed=false`
- [x] 3.3 `nle_snapshot(ctx) -> bytes` / `nle_restore(ctx, bytes)` per the strategy chosen in 1.4, with a build/struct-version tag — `nle_fr_snapshot`/restore/destroy (`nle_fast_reset.c`)
- [x] 3.4 `nle_tune_t` sub-struct in `nle_ctx_t` + `nle_get_tune`/`nle_set_tune`; wire each knob to its engine read site (makemon, damage, vision/fog, mklev doors/levels, attrs, luck) — X-macro `NLE_TUNE_FIELDS`, 12 knobs wired
- [ ] 3.5 `nle_load_level(ctx, ...)` — load a custom level/scenario description — **OPEN** (gates §6)

## 4. Standalone ctypes/cffi binding (`_engine`)

- [x] 4.1 Create the `_engine` module: load `libnethack.so`, declare argtypes/restypes, allocate observation buffers
- [x] 4.2 Implement start/step/end + `nle_get_obs` fill into numpy buffers
- [x] 4.3 Derive the action mapping from the engine's action table; assert compass/misc enums (resolves OQ3/R3) — validated via GATE A golden parity
- [ ] 4.4 Expose seed, snapshot/restore, tune get/set, and load_level through the binding — **PARTIAL: seed/snapshot/restore/get_tune/set_tune exposed; `load_level` not (blocked by 3.5)**

## 5. Harness integration

> Approach taken: a parallel `EngineEnv` (`nethack_core/engine_env.py`) was built rather than
> rewriting `NetHackCoreEnv` in place. The remaining integration is to make `EngineEnv` canonical
> and retire the nle-backed `NetHackCoreEnv`.

- [ ] 5.1 Rewrite `NetHackCoreEnv.seed/reset/step` to drive `_engine`; build `CoreObservation` from binding buffers — **OPEN: `env.py` still `import nle`; the new path lives in `EngineEnv`, not wired into `NetHackCoreEnv`**
- [ ] 5.2 Keep `observations.py` `shape()` and consumers unchanged; verify `StructuredObservation` field/type parity — **OPEN (depends on 5.1)**
- [ ] 5.3 Update `skills.py` action-index mapping and `last_observation`/`_observation_keys` reads to the new binding — **OPEN**
- [ ] 5.4 Replace `legacy/replay.py` action-replay internals with snapshot/restore; preserve any trajectory surface the replay viewer consumes — **OPEN**
- [x] 5.5 Add `snapshot()`/`restore()` and a `tune` surface (`tune.get()`/`tune.set(**knobs)`) on the env — present on `EngineEnv` (`snapshot`/`restore`/`get_tune`/`set_tune`)

## 6. Level customization + curriculum migration

- [ ] 6.1 Re-express curriculum tiers' MiniHack `des_file`s via `nle_load_level` (or snapshot presets) — **OPEN (blocked by 3.5)**
- [ ] 6.2 Remove the MiniHack git dependency and confirm tiers run without it — **OPEN: `minihack` still a hard dep**
- [ ] 6.3 Decide and document the preset/level format (resolves OQ4) — **OPEN**

## 7. Parity, determinism, and cutover gate

- [x] 7.1 Golden-trace parity test: record an `nle` trace, replay same seed/actions through `_engine`, assert byte-identical tty_chars/blstats/message for N steps (R2) — **GATE A PASS**: glyphs/chars/colors/blstats byte-perfect; tty_chars+message accepted as "binding-native" (cosmetic refresh-point diff, same engine) — `test_golden_parity.py`
- [x] 7.2 Determinism test: two same-seed rollouts are step-identical (R4) — `test_engine_env.py::test_determinism_same_seed`, `test_snapshot.py::test_replay_determinism`
- [x] 7.3 Snapshot round-trip + multi-level + version-guard tests (spec: state-snapshot) — `test_snapshot.py` (round-trip, repeated-restore byte-exact, independent snapshots, no-leak) + `test_snapshot_multilevel.py` (GATE B level-file bundling)
- [x] 7.4 Per-knob effect tests incl. reset-time vs live timing (spec: difficulty-tuning) — `test_tune.py` (hunger/reveal/fog effects, all-knobs settable+safe, snapshot-captures-tune) + `test_generation.py` (tune-at-start before generation)
- [ ] 7.5 Only after 7.1–7.2 pass: remove `nle>=1.3.0` from all `pyproject.toml`/lockfiles and delete the `nle` code path — **OPEN — the headline cutover** (gates pass; not yet executed)
- [ ] 7.6 Full eval smoke run end-to-end through the new engine — **OPEN (depends on 5.x + 7.5)**

## 8. Docs

- [ ] 8.1 Document the new engine layer: binding, snapshot API, tune knobs (with timing + ranges), level customization — **OPEN**
- [ ] 8.2 Record open-question resolutions (OQ1–OQ5) and final API signatures — **PARTIAL: OQ1/OQ3 captured in design.md; OQ4 (level format) + final cutover signatures pending**
