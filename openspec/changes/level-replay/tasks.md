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
