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
