# Tasks — level-replay

> Finishes the `custom-nethack-engine` migration. Absorbs that change's remaining open
> tasks (§3.5, §5, §6, §7.5–7.6, §2.3–2.4, §8, Pillar 2 knobs).

## 0. De-risking spikes (gate their workstreams) — BOTH DONE 2026-06-11
- [x] 0.1 **Spike — standalone level load: FEASIBLE (proven end-to-end).** save=`savelev(WRITE_SAVE)`→slurp bytes; load=stamp→`open_levelfile`→`minit`→`savelev(-1,FREE_SAVE)`→`getlev`→re-seat hero on stairs→`vision_reset`. CONSTRAINT: load is **two-phase** — mutate state in `nle_load_level`, render on the NEXT `nle_step` (rendering inside load jumps a dead fcontext → SIGSEGV). Also scrub the rl mirror to avoid prior-level glyph residue. Blob = standard levelfile, portable across fresh same-build games (not version-portable). ~135-line fork C diff (saved at `/tmp/spike_fork.diff`, reverted).
- [x] 0.2 **Spike — mid-episode reseed: FEASIBLE, NO fork C needed.** Gameplay RNG is ISAAC64 in `nle_ctx_t->rng_state[2]` (captured by snapshot); `nle_set_seed` (already exported) → `set_random`→`isaac64_init` fully re-seeds it. Order: `restore` → `nle_set_seed(core,disp)` → `step`. Proven: 16/16 reseeds diverged; no-reseed byte-identical; reproducible per seed. Just needs a ctypes binding + `EngineEnv.branch`.

## 1. Fork C API (submodule → fork branch + PR)
- [ ] 1.1 `nle_save_level(ctx, &len) -> blob` + `nle_load_level(ctx, bytes, len) -> int` per the proven Spike 0.1 approach (two-phase load; hero re-seat + `vision_reset`; rl-mirror scrub). Decls in `include/nle.h` near the seed API; add `#include <fcntl.h>`,`#include "lev.h"`
- [ ] 1.2 Wire remaining Pillar 2 generation knobs to their `mklev`/spawn read-sites: `mob_spawn`, `trap_density`, `locked_door`, `corridor_connectivity`, `room_size`
- [ ] 1.3 Open the fork PR; after merge, bump the `third_party/NetHack` submodule pointer in the harness

## 2. Binding surface (`_engine` / `EngineEnv`)
- [ ] 2.1 Expose `save_level(path)` / `load_level(path)` on `RawEngine` and `EngineEnv` against a floor-library dir (closes custom-nethack-engine §4.4 partial); honor the two-phase render (step once after load)
- [ ] 2.2 Expose the new generation knobs through the tune surface; assert they round-trip
- [ ] 2.3 Bind the already-exported `nle_set_seed` as `RawEngine.reseed(core, disp)`; implement `EngineEnv.branch(n, reseed=True)` = snapshot → for each: restore → reseed(distinct) → return continuation (per Spike 0.2)
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
