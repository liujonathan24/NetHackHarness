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

**RISK / SPIKE 1 — standalone load.** GATE B round-trips level files *inside a snapshot* (full dungeon context present). Loading a single concrete level as a *starting* level is a new entry point: the dungeon-context fields (`u.uz`, dungeon/branch tables, `level` linkage) must be consistent or `getlev` mis-binds. De-risk with an early spike: save floor at dlvl N, end, fresh `nle_start`, `load_level`, assert the obs grid matches the saved floor and play proceeds.

## 2. Snapshot + explore

Replace `legacy/replay.py`'s `(seed, action_sequence)` re-execution with snapshot/restore, and add divergent branching.

- `EngineEnv.branch(n, reseed=True) -> list[handle|obs]` — snapshot the current state, then produce N continuations. With `reseed=True`, **reseed the RNG after each restore** so random-chance events (monster spawns, search success, door outcomes) diverge across branches. With `reseed=False`, branches are identical (RNG is captured by the snapshot) — useful as a control.
- Plain `snapshot()`/`restore()` stay exact (existing behavior, unchanged).

**Decision — non-determinism comes from reseed, not from the snapshot.** A restore is byte-exact (RNG included), so divergence must be injected. We reuse `nle_set_seed`'s display/core seed path, applied post-restore.

**RISK / SPIKE 2 — mid-episode reseed.** `nle_set_seed` is normally applied before `nle_start`. Reseeding the core RNG mid-episode (after restore) to fork the random stream is unproven. Spike: restore the same snapshot twice with two different reseeds, step the same action, assert the outcomes can differ (e.g. spawn/search variance over K steps) while `reseed=False` stays identical. If mid-episode core reseed is unsafe, fall back to perturbing only the display RNG or document branch as control-only.

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
