# Tasks — level-replay

> Finishes the `custom-nethack-engine` migration. Absorbs that change's remaining open
> tasks (§3.5, §5, §6, §7.5–7.6, §2.3–2.4, §8, Pillar 2 knobs).

## 0. De-risking spikes (gate their workstreams) — BOTH DONE 2026-06-11
- [x] 0.1 **Spike — standalone level load: FEASIBLE (proven end-to-end).** save=`savelev(WRITE_SAVE)`→slurp bytes; load=stamp→`open_levelfile`→`minit`→`savelev(-1,FREE_SAVE)`→`getlev`→re-seat hero on stairs→`vision_reset`. CONSTRAINT: load is **two-phase** — mutate state in `nle_load_level`, render on the NEXT `nle_step` (rendering inside load jumps a dead fcontext → SIGSEGV). Also scrub the rl mirror to avoid prior-level glyph residue. Blob = standard levelfile, portable across fresh same-build games (not version-portable). ~135-line fork C diff (saved at `/tmp/spike_fork.diff`, reverted).
- [x] 0.2 **Spike — mid-episode reseed: FEASIBLE, NO fork C needed.** Gameplay RNG is ISAAC64 in `nle_ctx_t->rng_state[2]` (captured by snapshot); `nle_set_seed` (already exported) → `set_random`→`isaac64_init` fully re-seeds it. Order: `restore` → `nle_set_seed(core,disp)` → `step`. Proven: 16/16 reseeds diverged; no-reseed byte-identical; reproducible per seed. Just needs a ctypes binding + `EngineEnv.branch`.

## 1. Fork C API (submodule → fork branch + PR)
- [x] 1.1 `nle_save_level(ctx, &len) -> blob` + `nle_load_level(ctx, bytes, len) -> int` per the proven Spike 0.1 approach (two-phase load; hero re-seat + `vision_reset`; rl-mirror scrub). Decls in `include/nle.h` near the seed API; add `#include <fcntl.h>`,`#include "lev.h"` — DONE fork `b7d0423`
- [x] 1.2 Wire remaining Pillar 2 generation knobs to their `mklev`/spawn read-sites: `mob_spawn`, `trap_density`, `locked_door`, `corridor_connectivity`, `room_size` — DONE fork `70a7175` (knob<=0 guarded, 1.0 parity holds)
- [~] 1.3 Open the fork PR; after merge, bump the `third_party/NetHack` submodule pointer — submodule bumped provisionally (harness `86d205d` → fork `70a7175`); fork branch PUSH + PR still pending (final A4 at end of build)

## 2. Binding surface (`_engine` / `EngineEnv`)
- [x] 2.1 Expose `save_level(path)` / `load_level(path)` on `RawEngine` and `EngineEnv` (closes custom-nethack-engine §4.4 partial); two-phase render honored; round-trip + hero-placement tested. Harness `3144667`+`b1b2178`, fork hero fix `22cc153`
- [x] 2.2 Expose the new generation knobs through the tune surface; assert they round-trip — DONE (generic catalog; `9a10b02`)
- [x] 2.3 Bind the already-exported `nle_set_seed` as `RawEngine.reseed(core, disp)`; implement `EngineEnv.branch(n, reseed=True)` = snapshot → for each: restore → reseed(distinct) → return continuation — DONE `55559d5` (8/8 branches diverge, 1/8 without)
- [x] 2.4 Tests: save→load round-trip (loaded floor == saved), generate-N-floors smoke, new knobs settable + safe — DONE `b1b2178`+`9a10b02`

## 3. Make `EngineEnv` canonical (harness integration)
- [x] 3.1 `NetHackCoreEnv.seed/reset/step` delegate to `EngineEnv` for native tasks; reward via swappable `RewardModel` (score+dlvl*50+xp*50); native path imports neither gym nor nle. `f065d93`+`d110e04`
- [x] 3.2 Native env observation shape parity (21,79)/blstats; cutover tests `test_core_env_cutover.py` green
- [x] 3.3 **Harness action-layer migration to semantics-native — DONE `99da719`+`1c6fcbe`.** `nethack_core/actions.py` (nle-free IntEnums = named keystrokes); `helpers.py`/`skills.py`/`pathfinding.py`/`nethack.py` repointed; index layer deleted (keystroke is the single ABI for both backends); `last_observation`/`observation_keys`/`frontier_blacklist_current` are env-native properties. Harness tests 39→17 fail (22 fixed, 0 new); native path nle-free. REMAINING nle coupling: skills.py glyph predicates (`glyph_is_monster/pet`, `MAXPCHARS`) — handle in Phase F.
- [x] 3.4 Snapshot/restore + tune + branch surface on the canonical env (delegated from `EngineEnv`)

## 4. Snapshot + explore (replace `legacy/replay.py` re-execution)
- [x] 4.1 `legacy/replay.py` (seed,actions) replay works as-is on the deterministic engine (snapshot/restore available via EngineEnv for O(1) clone); old recordings viewer-readable
- [x] 4.2 `branch(n, reseed=True)` variance / `reseed=False` identical / plain restore byte-exact — DONE `test_branch.py`+`test_snapshot.py`
- [x] 4.3 `test_replay.py` 6 green on the engine; `record_demo.py` smoke ok

## 5. Secure state checkpoint + modification (REPLACES curriculum migration — design pivot 2026-06-11)
> Abandon the MiniHack mini-task tiers (delete, don't migrate). Build a curated,
> validated state-modification layer on top of checkpointing. v1 mutations:
> `hp`/`max_hp`, `goto_depth` (skip e.g. 2→4), `gold`, `xp_level`, `hunger`.
> Applied both live (`EngineEnv.modify(**changes)`) and via an at-reset config.
- [x] 5.1 Fork C: secure state setters `hp`/`max_hp`/`gold`/`xp_level`/`hunger` + `goto_depth(n)` (deferred `schedule_goto`); name-keyed `nle_set_state` dispatch — DONE fork `e991505`
- [x] 5.2 Binding + `EngineEnv.modify(**changes)` (live), whitelist+bounds validated — DONE `efd3c8a`
- [x] 5.3 At-reset config `EngineEnv(modify=...)`/`reset(modify={...})`; `NetHackCoreEnv` pass-through — DONE `efd3c8a`
- [x] 5.4 Delete the 3 MiniHack tiers from `curriculum.py` (13→10 native tiers); remove `minihack` dep — DONE `074483b`
- [x] 5.5 Tests: mutations round-trip in blstats, `goto_depth` lands dlvl 4, out-of-range/unknown rejected, at-reset config — DONE `test_modify.py` (5 tests; suite 94 green)

## 6. The nle cutover — nle + minihack FULLY REMOVED (`a8c47c6`+`074483b`)
- [x] 6.1 Native path imports no nle; pure-Python `nethack_core/glyphs.py` (exact parity vs nle) replaces the last glyph-helper coupling; MiniHack gym branch raises
- [x] 6.2 `nle`/`minihack` removed from all pyproject; `uv sync --all-packages` resolves clean; nle/minihack uninstalled
- [x] 6.3 Acceptance grep clean (only comments/docstrings; runtime imports zero) — golden oracle-recorder script left as documentation (not collected)
- [x] 6.4 `Dockerfile.prime` builds the submodule via `build_engine.sh` (no nle wheel) — DONE (not docker-build-tested on this node)
- [x] 6.5 `image_render.py` degrades gracefully without minihack (IMG path → `img` optional extra); tty path works

## 7. Verify + docs
- [x] 7.1 GATE A golden-trace parity + determinism green (engine suite 100; harness 17 fail = pre-existing baseline, 0 new)
- [x] 7.2 Full eval smoke — DEFERRED to the user's vf-eval/API setup (not runnable on this node; engine+harness suites green stand in). Accepted deviation.
- [x] 7.3 `docs/engine-layer.md` + README install (submodule + build_engine.sh + uv sync --all-packages) — DONE `5ccc0a8`
- [x] 7.4 OQ/signatures in design doc; parent `custom-nethack-engine` marked SUPERSEDED — DONE `5ccc0a8`
- [x] 7.5 Phase D — `legacy/replay.py` (seed,actions) replay works on the deterministic engine; `test_replay.py` 6 green (no rewrite needed)
