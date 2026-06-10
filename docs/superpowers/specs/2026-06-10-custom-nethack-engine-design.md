---
comet_change: custom-nethack-engine
role: technical-design
canonical_spec: openspec
---

# Custom NetHack Engine — Technical Design

OpenSpec is the source of truth for requirements (`openspec/changes/custom-nethack-engine/`).
This doc captures HOW: implementation approach, grounded in the fork's actual source.

## 1. Fork reality (verified against source)

The fork (`liujonathan24/NetHack`, NLE 0.9.0 / NetHack 3.6.6 lineage) is more capable
than the open-phase proposal assumed. Verified by reading the cloned source:

- **Per-env state**: all process globals migrated into `nle_ctx_t` (`src/include/nle.h:97–1096`),
  reached via initial-exec TLS `current_nle_ctx`.
- **Per-env bump arena**: every heap allocation (C `alloc()` in `alloc.c`, and C++ `operator new`
  via `nle_arena_cpp.cc`) is routed into a per-env mmap'd arena
  (`s_arena_base`/`s_arena_used`/`s_arena_cap` on `nle_ctx_t`). Therefore every heap pointer
  reachable from libnethack's writable LOAD segments points into the arena.
- **Snapshot primitive already exists**: `nle_fast_reset.c` exposes
  `nle_fr_snapshot(nle_ctx_t*)` / `nle_fr_restore(nle_ctx_t*, snap)` / `nle_fr_destroy(snap)`,
  which memcpy `{ctx, coroutine stack, arena[0..arena_used]}`. Because the arena is restored
  to the **same base address**, pointer aliasing is a non-issue.
- **Public C API** (`include/nledl.h`): `nle_start`, `nle_step`, `nle_reset`, `nle_end`,
  plus `nle_set_seed(ctx, core, disp, reseed)` and `nle_get_seed` — seeding already exists.
- **Observation buffers** (`include/nleobs.h`, `struct nle_observation`): caller allocates
  buffers (`glyphs`, `chars`, `colors`, `blstats`, `message`, `tty_chars/colors/cursor`,
  `inv_*`, …); `nle_step` fills them. `NLE_BLSTATS_SIZE == 27` (harness assumes 26 — align).
- **Settings** (`nle_settings`): `hackdir`, `options`, `wizkit`, `spawn_monsters`, `ttyrecname` —
  the existing reset-time config surface. `spawn_monsters` is already a difficulty toggle.
- **Special-level loader present**: `sp_lev.c` interprets compiled des opcodes (stock NetHack),
  so declarative `.des` layouts remain available.

Consequence: most of the "new C API" in the proposal is **already present**; we mostly bind.
The genuinely new C work is `nle_tune_t` + its read-sites, and snapshot→bytes serialization.

## 2. Context / current state

Today `NetHackCoreEnv` (`environments/nethack/nethack_core/env.py`) wraps `gym.make` over
`nle 1.3.0`, consuming the NLE obs dict and stepping integer actions; `observations.py` `shape()`
turns `CoreObservation` into `StructuredObservation`. Curriculum tiers
(`curriculum.py`) embed MiniHack des-file strings via `MiniHack-Skill-Custom-v0`. Replay is
O(n) action-replay (`legacy/replay.py`).

## 3. Goals / Non-Goals

**Goals:** full cutover off `nle`; standalone ctypes binding; reuse `observations.py`;
O(arena) snapshot/restore; parametric difficulty via `nle_tune_t`; level customization via
knobs + des superset; determinism preserved.

**Non-Goals (v1):** multiple live `nle_ctx_t` per process (sequential snapshots on one env
suffice); persistent cross-process snapshots (in-process only for v1); rewriting generation
algorithms (we parametrize existing ones, not replace them); on-disk savefile parity.

## 4. Decisions

### D1 — Binding: ctypes over the existing nledl API
The `_engine` module `ctypes.CDLL`-loads the engine and declares `argtypes`/`restypes` for
`nle_start/step/reset/end`, `nle_set_seed/get_seed`, `nle_fr_snapshot/restore/destroy`, and the
new `nle_get_tune/set_tune`. Observation buffers are numpy arrays whose pointers are stored in a
`nle_obs` struct; `nle_step` fills them in place. No PufferLib, no NLE Python layer.

### D2 — Reuse CoreObservation / observations.py
`NetHackCoreEnv` builds `CoreObservation` from the binding's buffers; `shape()` and all
consumers are byte-compatible. Only the obs *source* changes. Align `blstats` length to 27.

### D3 — Snapshot = wrap nle_fr_snapshot; spike gates completeness
`env.snapshot()` wraps `nle_fr_snapshot` (in-process: hold the opaque handle; no serialization).
Cost is `O(arena_used + stack + sizeof ctx)` — independent of step count. **The build leads with
the OQ1 spike**: snapshot @ dlvl1 → descend to dlvl3 → restore → re-descend → assert levels 1–3
identical. NetHack writes inactive levels to disk (`goto_level` → `savelev`/`getlev` to
`<hackdir>/<s_lock>.<ledger#>`, `files.c`), which the arena snapshot may NOT capture.
Decision tree from the spike:
- PASS (levels in arena) → snapshot is complete as-is.
- FAIL → bundle `<hackdir>/<s_lock>.*` level files into the snapshot blob (simplest), or route
  level I/O to memory (memfd/tmpfs/in-arena). Python API is identical either way.

### D4 — Difficulty via nle_tune_t, three layers, two timings
A `nle_tune_t` sub-struct of `nle_ctx_t`, read at decision sites. Python surface:
`env.tune.get() -> dict` / `env.tune.set(**knobs)`. Timing: **reset/generation-time (R)** knobs
take effect at the next reset (topology + per-level generation); **live (L)** knobs take effect
on the next step. The binding signals when a R-knob is set mid-episode (applies next reset).
The full catalog is the canonical contract in the `difficulty-tuning` delta spec (see §6).
Extensibility is the design invariant: new knob = one field + one read site, zero binding change.

### D5 — Levels: parametric knobs primary, des superset, snapshot presets
Layer 1–2 knobs are the primary "edit the generator from Python" surface. `.des` files stay
(`sp_lev.c` present) for hand-drawn declarative layouts. Snapshot presets pin reproducible
starts. Curriculum tiers migrate off MiniHack onto knobs/des/presets; MiniHack dep removed.

### D6 — GameConfig composes everything
A single Python `GameConfig` composes start-state + topology + generation + engine knobs +
optional des `level_overrides` + optional `preset_snapshot`. Reproducible by seed, snapshot-able.

### D7 — Submodule + native build
Fork pinned as a git submodule (e.g. `third_party/NetHack`); build runs
`make -C src/build nethack -j` → `libnethack.so` + data; binding locates it via packaged path /
env var; missing `.so` fails fast. `Dockerfile.prime` builds the submodule instead of the `nle`
wheel (toolchain already present).

## 5. MiniHack comparison (why this dominates)

MiniHack is a content-placement layer (Python `LevelGenerator` → des → `sp_lev`). It cannot
touch engine mechanics, offers no continuous/parametric generation, is single-level, has no
state cloning, no mid-episode mutation, and scales poorly (subprocess model). The fork attacks
three layers MiniHack never reaches (engine mechanics, parametric generation, topology), keeps
des as a strict subset, adds O(arena) snapshots and live mutation, and runs in-process at scale.

## 6. Spec Patch — difficulty-tuning delta spec

The knob catalog (the contract between fork edits and the Python surface) is written back into
`openspec/changes/custom-nethack-engine/specs/difficulty-tuning/spec.md` as the canonical v1
knob set, each tagged `{layer, timing R|L, type, default, C site}`, plus requirements that
(a) defaults reproduce vanilla, (b) R-vs-L timing is honored, (c) the catalog is extensible.
No second requirements spec is created here.

## 7. Test strategy

1. **Golden-trace parity (cutover gate)**: record an `nle 1.3.0` trace (seed + actions); replay
   through `_engine`; assert byte-identical `tty_chars`/`blstats`/`message` for N steps. `nle` is
   not deleted until this passes.
2. **Determinism**: two same-seed rollouts are step-identical.
3. **Snapshot**: round-trip parity; multi-level round-trip (the OQ1 spike, promoted to a test);
   restore is step-count-independent.
4. **Knobs**: per-knob effect test; defaults reproduce vanilla; R-vs-L timing behaves
   (R applies next reset, L applies next step).
5. **Levels**: a migrated curriculum tier runs without MiniHack installed.

## 8. Risks / Trade-offs

- **R1 snapshot completeness (gating)** → OQ1 spike first; bundle level files if needed.
- **R2 obs parity** → golden-trace gate before deleting `nle`; mind `blstats` 27 vs 26.
- **R3 action encoding** → same NLE action table expected; assert via parity test.
- **R4 seeding** → `nle_set_seed(reseed=0)`; verified by determinism test.
- **R5 build/portability** → document submodule build; cache in Docker; fail fast.
- **R6 snapshot build-specificity** → in-process v1 sidesteps it; tag blobs with build/struct
  version if/when persistence is added.
- **R7 breadth of "expose everything"** → catalog makes scope explicit and reviewable; knobs
  land incrementally, each with a test.

## 9. Open questions — resolutions

- **OQ1** snapshot completeness vs disk levels → **spike-gated**, leads the build (§4 D3).
- **OQ2** knob timing → **two-tier R/L**, canonical in the delta-spec catalog.
- **OQ3** action remap → **expected 1:1** (NLE action table); verified by parity test.
- **OQ4** level/preset format → **knobs primary + des superset + snapshot presets** (§4 D5).
- **OQ5** multi-ctx per process → **deferred**; v1 is sequential snapshots on one live env.
