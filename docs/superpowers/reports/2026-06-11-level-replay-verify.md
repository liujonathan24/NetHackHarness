# Verification Report: level-replay

Date: 2026-06-11
Mode: full
Base ref: `b20aaaac6bc475cec796b3817960e2b563b8ddc6`
Branch: `level-replay` (harness) + `feature/level-replay` (fork submodule)

## Summary

| Dimension    | Status                                              |
|--------------|-----------------------------------------------------|
| Completeness | All tasks `[x]` (eval-smoke deferred — see below)   |
| Correctness  | Spec requirements implemented + tested              |
| Coherence    | Matches design doc; nle/minihack fully removed      |

**Assessment: PASS.** The migration goal — run entirely on the fork engine, `nle`/`minihack` removed — is achieved and tested. One accepted deviation (eval-smoke deferred to the user's eval infra).

## Evidence

- **Engine suite:** `pytest environments/nethack/tests/ -q` → **100 passed** with `nle`/`minihack` uninstalled.
- **Harness suite:** `pytest tests/ -q` → **17 failed / 399 passed / 4 skipped**. The 17 are byte-identical to the pre-cutover baseline (pre-existing, unrelated: verifiers-contract, rollout_view fixtures, resource_tracker teardown noise). **Zero new failures** introduced by this change.
- **nle removal acceptance:** `grep -rn "import nle\|from nle\|import minihack\|nle.nethack"` across `nethack_core/` + `nethack_harness/` → only comments/docstrings; **zero runtime imports**. `uv sync --all-packages` resolves clean without `nle`/`minihack`.
- **Determinism + parity (GATE A):** `test_golden_parity.py`, `test_engine_env.py::test_determinism_same_seed`, `test_snapshot.py` green across the cutover.

## Requirements → implementation

- **nethack-engine (sole backend; branch):** `NetHackCoreEnv`→`EngineEnv`; `import nle` gone; `glyphs.py` (exact parity vs nle) + `actions.py` (semantics-native) replace the harness coupling; `EngineEnv.branch(n, reseed)` (8/8 diverge / 1/8 control). ✓
- **level-customization (generate/save/load; MiniHack removed; state modification):** `nle_save_level`/`nle_load_level` + `EngineEnv.save_level`/`load_level` (round-trip + hero-placement tested); MiniHack tiers deleted + `minihack` dep dropped; secure `modify()` (`hp`/`max_hp`/`gold`/`xp_level`/`hunger`/`goto_depth`, whitelist+bounds, live + at-reset). ✓
- **difficulty-tuning (new gen knobs):** `mob_spawn`/`trap_density`/`locked_door`/`corridor_connectivity`/`room_size` wired (knob<=0 guarded, 1.0 = byte-parity), settable+safe tests. ✓

## Coherence

Implementation matches the design doc (concrete savelev/getlev blobs; snapshot+reseed branching; cutover) and the mid-build design pivot (drop MiniHack, add secure state checkpoint+modification) is captured in the design doc + delta spec. Two de-risking spikes (standalone load two-phase contract; mid-episode reseed) were run and proven before building.

## Accepted deviation

- **7.2 Full eval smoke** — DEFERRED. A full end-to-end LLM rollout needs the user's vf-eval/verifiers + API setup, not runnable on this node. The engine suite (100) + harness suite (0 new failures) + a manual native rollout stand in. To be run by the user against their eval harness.

## Branch handling

Decision: **keep the branch; the user pushes.** The fork branch `feature/level-replay` (`b7d0423`→`e991505`, 5 commits) and the harness `level-replay` branch are committed locally and unpushed. The user will push (the fork branch MUST be pushed for the submodule pointers to resolve on any remote) and open the fork PR. SSH remotes are configured.
