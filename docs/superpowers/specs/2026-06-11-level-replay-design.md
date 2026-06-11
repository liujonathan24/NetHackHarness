---
comet_change: level-replay
role: technical-design
canonical_spec: openspec
---

# Level-Replay — Technical Design

Finishes the `custom-nethack-engine` migration. OpenSpec proposal/specs are the source of truth for WHAT; this is HOW. Three workstreams: the **cutover** (make `EngineEnv` canonical, remove `nle`/`minihack`), the **level-file-blob model** (generate/save/load floors), and **snapshot-based exploration**.

## 1. Level-file-blob model (engine/Python only)

The universal currency is NetHack's concrete level-file blob — the `savelev`/`getlev` binary format the GATE B work already bundles and restores inside snapshots.

- **Generate** — native engine generation (seed + the `nle_tune` generation knobs) yields "dungeon level X" floors at runtime, arbitrary count. No des authoring. Already driven by `EngineEnv`.
- **Save** — new fork primitive `nle_save_level(ctx, buf, len) -> n` built on `savelev`; dumps the *current* floor to a portable blob. Surfaced as `EngineEnv.save_level(path)` writing to a floor-library dir.
- **Load** — `nle_load_level(ctx, bytes)` via `getlev`, surfaced as `EngineEnv.load_level(path)`; starts a session on the saved floor.
- **Curriculum** — the 3 static des tiers (`empty_room`, `solo_combat`, `multi_combat`) are compiled once (des → build-time `lev_comp` → instantiate → `nle_save_level`), shipped as `.blob` assets under `nethack_core/levels/`, loaded through the same `load_level` path. The `des_file=None` tiers (`mini_dungeon`, `full_dungeon_easy`, `full_nle`) stay native generation. `minihack` is removed.

**Decision — concrete blobs, not des templates.** NetHack has two level formats: `lev_comp` *templates* (authored, may randomize on instantiation) and `savelev`/`getlev` *concrete* instances (fully determined). We standardize on concrete blobs so a saved floor reloads exactly and everything flows through one load path. Authoring/`LevelGenerator`-style runtime des is explicitly out of scope (never used; YAGNI).

**SPIKE 1 — standalone load: RESOLVED ✅ FEASIBLE (proven end-to-end).** save = `savelev(fd, ledger_no(&u.uz), WRITE_SAVE)` (no `FREE_SAVE`, live level survives) → slurp the levelfile bytes; load = stamp bytes to the `<lock>.<ledger>` path → `open_levelfile` → `minit()` → `savelev(-1, FREE_SAVE)` (tear down live level) → `getlev(fd, hackpid, ledger, FALSE)` → re-seat hero on `xupstair`/saved pos → `vision_reset()`. **Hard constraint: load is two-phase** — `nle_load_level` mutates state only; the re-render must run on the next `nle_step` (rendering inside load calls the rl window port which yields via `jump_fcontext` to a dead context → SIGSEGV). For same-seed fresh start, `u.uz`/dungeon tables/role are already correct (only hero placement + vision need fixing); for a different dungeon slot also set `u.uz`/`u.uz0` + `reset_rndmonst`. Scrub the rl mirror to avoid prior-level glyph residue. Blob is a standard self-contained levelfile, portable across fresh same-build games (not version-portable). Decls go in `include/nle.h` near the seed API; needs `#include <fcntl.h>` + `#include "lev.h"`.

## 2. Snapshot + explore

Replace `legacy/replay.py`'s `(seed, action_sequence)` re-execution with snapshot/restore, and add divergent branching.

- `EngineEnv.branch(n, reseed=True) -> list[handle|obs]` — snapshot the current state, then produce N continuations. With `reseed=True`, **reseed the RNG after each restore** so random-chance events (monster spawns, search success, door outcomes) diverge across branches. With `reseed=False`, branches are identical (RNG is captured by the snapshot) — useful as a control.
- Plain `snapshot()`/`restore()` stay exact (existing behavior, unchanged).

**Decision — non-determinism comes from reseed, not from the snapshot.** A restore is byte-exact (RNG included), so divergence must be injected. We reuse `nle_set_seed`'s display/core seed path, applied post-restore.

**SPIKE 2 — mid-episode reseed: RESOLVED ✅ FEASIBLE, no fork C needed.** Gameplay RNG is ISAAC64 (`USE_ISAAC64` defined); its state lives in `nle_ctx_t->rng_state[2]`, so the snapshot captures it (plain restore is byte-exact). `nle_set_seed` (already exported from `libnethack.so`) → `set_random` → `isaac64_init` fully overwrites the ISAAC64 context, and nothing re-clobbers it after restore. Mechanism for `branch`: `restore(handle)` → `nle_set_seed(core, disp, reseed)` → `step` (order matters — reseed AFTER restore). Proven: 16/16 distinct reseeds diverged from step 0; no-reseed restore byte-identical over 80 steps; reproducible per seed. Production work is binding-only: add the `nle_set_seed` ctypes binding + `RawEngine.reseed()` and wire `EngineEnv.branch`.

`legacy/replay.py`: the `(seed, actions)` recording format remains *readable* (the replay viewer reads stored frames, untouched), but the active clone/branch mechanism becomes snapshot-based. No migration of old recordings — the viewer already renders from stored frames.

## 3. The cutover

- **`EngineEnv` canonical.** `NetHackCoreEnv.seed/reset/step` become a thin adapter delegating to `EngineEnv`, building `CoreObservation` from binding buffers; then the nle-backed internals are deleted. `observations.py shape()` and `StructuredObservation` field/type parity is asserted against the pre-cutover shape. `skills.py` action mapping + `last_observation`/`_observation_keys` reads move to the binding.
- **Remove nle/minihack.** Delete `import nle`/`import minihack`; drop `nle>=1.3.0` + `minihack` from every `pyproject.toml` + lockfile; `Dockerfile.prime` builds the submodule via `build_engine.sh` instead of the nle wheel. **Acceptance:** `grep -rn "import nle\|from nle\|minihack"` clean outside archived/legacy docs; `uv sync` resolves without them.
- **`image_render.py` tileset.** Dropping `minihack` removes its `GlyphMapper` tile source. Bundle/vendor a tileset (the `NETHACK_TILESET` override already exists); small separate step.
- **Remaining generation knobs** — wire `mob_spawn`/`trap_density`/`locked_door`/`corridor_connectivity`/`room_size` to their `mklev`/spawn read-sites; settability + smoke (no crash, value round-trips, floor still generates), since their effects are mostly off-screen and not obs-diff-testable.

## Sequencing & gates

1. **Spikes first** — Spike 1 (standalone level load) and Spike 2 (mid-episode reseed). Both gate their workstreams; resolve before building on them.
2. Fork C: `nle_save_level` + `nle_load_level` + remaining knob read-sites → fork PR → bump submodule.
3. Binding + `EngineEnv`: `save_level`/`load_level`/`branch`; make `NetHackCoreEnv` delegate; `skills.py`/observation parity.
4. Curriculum: compile tiers to blobs; behavioral-smoke parity; drop `minihack`.
5. Cutover: remove `nle`; Docker; tileset.
6. Verify: GATE A parity + determinism green; full eval smoke; docs.

Hard gates (inherited): GATE A parity + determinism must stay green across the cutover. Two-repo rule: engine C → fork branch + PR; harness bumps the submodule pointer.

## Testing strategy

- **Level model:** `save_level`→`load_level` round-trip (loaded floor's obs grid == saved); generate-N-distinct-floors smoke; curriculum tiers behavioral smoke (loads, downstair present, specified monsters/room, short rollout runs). No byte-match, no minihack at test time.
- **Explore:** `branch(n, reseed=True)` shows outcome variance across branches over K steps; `reseed=False` is identical; plain `restore` byte-exact (existing snapshot tests cover this).
- **Cutover:** parity + determinism suites stay green; `grep` acceptance; `uv sync` clean; one full eval rollout end-to-end on the new engine.

## Open items resolved

- **OQ4 (level/preset format):** concrete `savelev`/`getlev` level-file blobs; curriculum assets under `nethack_core/levels/`.
- **Replay back-compat:** snapshot/restore is the mechanism; old `(seed,actions)` recordings stay viewer-readable, not re-executed; no migration.
- **Curriculum parity:** behavioral smoke (not byte-match); minihack fully dropped.

## Non-goals
- Runtime des authoring / `LevelGenerator`; `RewardManager` (we have `milestones.py`); a full search/MCTS harness over snapshots (separate change after the branch primitive); web-console UI for the floor library (engine/Python only here).
