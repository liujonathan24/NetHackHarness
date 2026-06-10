---
change: custom-nethack-engine
design-doc: docs/superpowers/specs/2026-06-10-custom-nethack-engine-design.md
base-ref: 1c88a700a3be0a14cc06ab533d267ea691098085
---

# Custom NetHack Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `nle` PyPI dependency with the struct-based NetHack fork (submodule + ctypes binding), and add O(arena) snapshots, a parametric `nle_tune_t` difficulty catalog, and level customization — full cutover.

**Architecture:** A standalone ctypes `_engine` module drives the fork's `libnethack.so` directly (no PufferLib/NLE-Python). `NetHackCoreEnv` builds `CoreObservation` from binding-filled buffers so `observations.py` is unchanged. Snapshots wrap the fork's existing `nle_fr_snapshot`; difficulty is a `nle_tune_t` sub-struct read at engine decision sites and surfaced as `env.tune`.

**Tech Stack:** Python 3.10+ (ctypes, numpy, gymnasium-shaped wrapper), C (NetHack 3.6.6 / NLE 0.9.0 fork), CMake/make build, pytest.

**Two repos:** Tasks tagged **[FORK]** land in the `liujonathan24/NetHack` submodule (the user develops there); untagged tasks land in this harness repo. Reference probe at `/tmp/nh-fork-probe`.

**Hard gates:**
- **GATE A (parity)** — Task 9 golden-trace parity must pass before Task 11 deletes `nle`.
- **GATE B (snapshot spike)** — Task 12 multi-level round-trip decides the snapshot blob strategy before Task 14 finalizes the API.

---

## Execution Environment (READ FIRST)

The engine is **Linux x86-64** (the committed `third_party/NetHack/src/build/libnethack.so` is `ELF x86-64`; the fork targets Linux: mmap arena, initial-exec TLS, `-Wl,-Bsymbolic-functions`, UNIX-only port assumptions). **All runtime tasks (ctypes smoke, GATE A parity, snapshot spike, knob effect-tests) must run on Linux x86-64** — Docker (`Dockerfile.prime`), a Linux dev box, or CI. On macOS/arm64, `ctypes` cannot load the ELF `.so`. Source-only tasks (writing `_engine.py`, build scripts, the catalog) can be authored anywhere, but TDD verification happens on Linux. Path layout note: the fork nests source — headers at `third_party/NetHack/src/include/`, C at `third_party/NetHack/src/src/`, build dir `third_party/NetHack/src/build` (`make -C third_party/NetHack/src/build nethack -j`).

## Two-Repo Workflow (READ FIRST)

Engine (C) changes and harness (Python) changes live in **different repositories and use different delivery mechanisms**:

| | Repo | Mechanism | Committed where |
|---|---|---|---|
| **Track F — engine** | `liujonathan24/NetHack` (the submodule) | **Pull Request to the fork repo**, reviewed + merged there | The harness records only a **submodule pointer bump** (`git add third_party/NetHack`) after each fork PR merges |
| **Track H — harness** | this repo | normal commits on the change branch | here |

**Rules:**
- **Never commit fork C changes into this repo.** Work in `third_party/NetHack` on a fork branch, push to the fork remote, open a PR there. Once merged, in this repo run `git -C third_party/NetHack checkout <merged-sha>` then `git add third_party/NetHack && git commit -m "build: bump NetHack submodule to <sha> (<feature>)"`.
- A `[FORK]` task is **done** only when its fork PR is merged **and** the submodule pointer is bumped here.
- The Comet state machine tracks the **harness** change only; fork PRs are external and referenced by SHA.
- **This plan executes BOTH tracks.** The agent does the engine C work too — creating fork branches in `third_party/NetHack`, pushing them to the fork remote, and opening PRs there — and pushes to both repos. The PR-to-fork mechanism is preserved (engine changes never land here as C diffs, only as submodule bumps); the difference is that the agent, not a separate human pass, authors them. Pushing to a remote is confirmed at push time.

**Dependency structure (good news — harness isn't fully blocked on fork PRs):**
The fork *already* exposes the obs buffers, seeding, and the `nle_fr_snapshot` primitive. So the binding, parity gate, and cutover (H tasks in Phases 1–3) run against the **current** fork with **no fork PR required**. The fork PRs add the *new* surface and gate only the features that need them:

```
Track H (this repo)                         Track F (fork PRs)
─────────────────────────────────          ─────────────────────────────────
Ph1 submodule+build+smoke      ◄── needs ── (current fork, as-is)
Ph2 obs binding + GATE A       ◄── may surface ──► F0  parity fix (only if GATE A fails)
Ph3 cutover + remove nle       ◄── (current fork)
Ph4 snapshot Python surface    ◄── needs ──► F1  nle_snapshot/restore + bytes (wraps nle_fr_*)
Ph4 GATE B spike               ◄── may surface ──► F2  level-file capture (only if spike fails)
Ph5 tune Python surface        ◄── needs ──► F3  nle_tune_t struct + get/set (defaults=vanilla)
Ph5 knob effect tests          ◄── needs ──► F4  tune read-sites by layer (L3→L2→L1/L0)
Ph6 level/GameConfig           ◄── needs ──► F5  des-from-buffer loader (only if not build-time)
```

So Phases 1–3 (binding + parity + cutover) can begin immediately; F1/F3/F4 fork PRs can be developed in parallel and are pulled in as their dependent harness phases start.

---

## Phase 1 — Submodule + build + ctypes smoke

### Task 1: Add the fork as a submodule

**Files:**
- Create: `.gitmodules`
- Create: `third_party/NetHack/` (submodule)

- [x] **Step 1: Add submodule pinned to current main**

```bash
git submodule add https://github.com/liujonathan24/NetHack third_party/NetHack
git -C third_party/NetHack rev-parse HEAD   # record the pinned commit
```

- [x] **Step 2: Verify checkout**

Run: `ls third_party/NetHack/src/include/nle.h third_party/NetHack/src/nle_fast_reset.c`
Expected: both paths exist.

- [x] **Step 3: Commit**

```bash
git add .gitmodules third_party/NetHack
git commit -m "build: add liujonathan24/NetHack fork as submodule (custom-nethack-engine)"
```

### Task 2: Build script for libnethack.so

**Files:**
- Create: `environments/nethack/nethack_core/build_engine.sh`

- [x] **Step 1: Write the build script** — DONE, but made **reproducible**: instead of `make -C src/build` (which relied on a stale committed CMakeCache pointing at an external PufferLib checkout), the script now does a clean `cmake -S third_party/NetHack/src -B src/build -DCMAKE_BUILD_TYPE=RelWithDebInfo` configure from the submodule source (deps vendored in `src/third_party/`), wiping the cache if it was generated from a different source tree. Also untracked the fork's committed 47MB `src/build/` artifacts (fork commit `bbdcb6e`, local-only — already gitignored).

- [x] **Step 2: Make executable + run** — DONE. Produces valid `ELF x86-64 libnethack.so` + `dat/` data files; `grep PufferLib CMakeCache.txt` = 0 (reproducible).

- [x] **Step 3: Commit** — DONE. Harness commit `09c99ba` "build: reproducible libnethack.so build script (cmake from submodule)". Submodule pointer NOT bumped (fork commit `bbdcb6e` unpushed — pending push+bump checkpoint).

### Task 3: `_engine` library locator + load

**Files:**
- Create: `environments/nethack/nethack_core/_engine.py`
- Test: `environments/nethack/tests/test_engine_binding.py`

- [ ] **Step 1: Write the failing test**

```python
# test_engine_binding.py
import pytest
from nethack_core import _engine

def test_library_loads():
    lib = _engine.load_library()
    assert lib is not None
    # public symbols exist (NOTE: engine has NO nle_reset — reset is via
    # nle_end+nle_start or the fast-reset/snapshot path. Verified against
    # libnethack.so exports + nle.h:1115-1119.)
    for sym in ("nle_start", "nle_step", "nle_end", "nle_set_seed", "nle_get_obs"):
        assert hasattr(lib, sym)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest environments/nethack/tests/test_engine_binding.py -v`
Expected: FAIL (`_engine` has no `load_library`).

- [ ] **Step 3: Implement the locator**

```python
# _engine.py
import ctypes, os
from pathlib import Path

class EngineNotBuilt(RuntimeError):
    pass

def _candidate_paths():
    env = os.environ.get("NLE_LIB_PATH")
    if env:
        yield Path(env)
    root = Path(__file__).resolve().parents[3]
    yield root / "third_party" / "NetHack" / "src" / "build" / "libnethack.so"

def library_path() -> Path:
    for p in _candidate_paths():
        if p and p.exists():
            return p
    raise EngineNotBuilt(
        "libnethack.so not found. Build it with "
        "environments/nethack/nethack_core/build_engine.sh "
        "(or set NLE_LIB_PATH). Toolchain: cmake/bison/flex/libbz2."
    )

_LIB = None
def load_library() -> ctypes.CDLL:
    global _LIB
    if _LIB is None:
        _LIB = ctypes.CDLL(str(library_path()))
    return _LIB
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest environments/nethack/tests/test_engine_binding.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add environments/nethack/nethack_core/_engine.py environments/nethack/tests/test_engine_binding.py
git commit -m "feat(engine): _engine library locator + ctypes load"
```

### Task 4: ctypes structs + lifecycle smoke

**Files:**
- Modify: `environments/nethack/nethack_core/_engine.py`
- Test: `environments/nethack/tests/test_engine_smoke.py`

- [ ] **Step 1: Declare nle_obs / nle_settings / nle_seeds_init ctypes mirrors**

Mirror `include/nleobs.h` exactly (sizes: `NLE_TERM_LI=24`, `NLE_TERM_CO=80`, `ROWNO*(COLNO-1)=21*79`, `NLE_BLSTATS_SIZE=27`, `NLE_MESSAGE_SIZE=256`, `NLE_INVENTORY_SIZE=55`, `NLE_INVENTORY_STR_LENGTH=80`). Allocate numpy buffers and point `nle_obs` fields at them via `ctypes.cast(arr.ctypes.data, ...)`. (Full struct in `_engine.py`; mirror every field of `struct nle_observation`.)

- [ ] **Step 2: Write the failing smoke test**

```python
# test_engine_smoke.py
from nethack_core import _engine

def test_start_step_end_runs():
    env = _engine.RawEngine()           # wraps nle_start/step/end + buffers
    obs = env.start(core=42, disp=42)
    assert obs.tty_chars.shape == (24, 80)
    obs2 = env.step(0)                   # action index 0
    assert obs2.tty_chars.shape == (24, 80)
    env.end()
```

- [ ] **Step 3: Run to verify it fails**

Run: `pytest environments/nethack/tests/test_engine_smoke.py -v`
Expected: FAIL (`RawEngine` undefined).

- [ ] **Step 4: Implement `RawEngine`** (set argtypes/restypes for `nle_start`, `nle_step`, `nle_reset`, `nle_end`, `nle_set_seed`; allocate buffers once; `start()` seeds via `nle_set_seed(ctx, core, disp, 0)` then calls `nle_start`; `step(a)` writes `obs.action=a`, calls `nle_step`, returns a `CoreObservation`-shaped view).

- [ ] **Step 5: Run to verify it passes**

Run: `pytest environments/nethack/tests/test_engine_smoke.py -v`
Expected: PASS (game starts, steps, ends).

- [ ] **Step 6: Commit**

```bash
git add environments/nethack/nethack_core/_engine.py environments/nethack/tests/test_engine_smoke.py
git commit -m "feat(engine): ctypes obs/settings structs + start/step/end smoke"
```

---

## Phase 2 — Observation binding + GATE A (parity)

### Task 5: Build CoreObservation from binding buffers

**Files:**
- Modify: `environments/nethack/nethack_core/_engine.py`
- Modify: `environments/nethack/nethack_core/env.py:36-54` (CoreObservation: allow blstats len 27)
- Test: `environments/nethack/tests/test_engine_obs.py`

- [ ] **Step 1: Write the failing test** — assert the binding produces a `CoreObservation` with the right shapes/dtypes (tty_chars (24,80) uint8, glyphs (21,79) int16, blstats (27,) and a documented index map, message (256,) uint8, inv_* present).

```python
from nethack_core import _engine
from nethack_core.env import CoreObservation

def test_binding_builds_core_observation():
    env = _engine.RawEngine()
    raw = env.start(core=1, disp=1)
    co = raw.to_core_observation()
    assert isinstance(co, CoreObservation)
    assert co.tty_chars.shape == (24, 80) and co.tty_chars.dtype.name == "uint8"
    assert co.glyphs.shape == (21, 79)
    assert co.blstats.shape[0] in (26, 27)
    env.end()
```

- [ ] **Step 2: Run to verify it fails** — `pytest environments/nethack/tests/test_engine_obs.py -v` → FAIL.

- [ ] **Step 3: Implement `to_core_observation()`** mapping buffers→`CoreObservation`; update the `CoreObservation` docstring/comment at `env.py:48` to note blstats may be length 27 (index map per `nleobs.h` `NLE_BL_*`).

- [ ] **Step 4: Run to verify it passes** — `pytest environments/nethack/tests/test_engine_obs.py -v` → PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat(engine): map binding buffers to CoreObservation (blstats=27)"`.

### Task 6: Record a golden NLE trace (reference oracle)

**Files:**
- Create: `environments/nethack/tests/golden/record_nle_trace.py`
- Create: `environments/nethack/tests/golden/trace_score_seed42.npz` (generated artifact)

- [ ] **Step 1: Write the recorder** — under the OLD `nle` path (still installed), run `NetHackScore-v0` with `set_initial_seeds(42,42,False)`, step a fixed action list (e.g. 200 deterministic actions), and save per-step `tty_chars`, `blstats`, `message` to `.npz`.

- [ ] **Step 2: Generate the artifact**

Run: `python environments/nethack/tests/golden/record_nle_trace.py`
Expected: `trace_score_seed42.npz` written with N steps.

- [ ] **Step 3: Commit** — `git add ... && git commit -m "test(engine): record golden nle trace (seed 42) as parity oracle"`.

### Task 7: GATE A — golden-trace parity test

**Files:**
- Create: `environments/nethack/tests/test_golden_parity.py`

- [ ] **Step 1: Write the parity test** — replay the SAME seed+actions through `_engine.RawEngine`, assert byte-identical `tty_chars`, `blstats` (aligning 26↔27 by index), and `message` at every step vs the `.npz`.

```python
import numpy as np
from nethack_core import _engine

def test_engine_matches_golden_nle():
    g = np.load("environments/nethack/tests/golden/trace_score_seed42.npz")
    env = _engine.RawEngine(); env.start(core=42, disp=42)
    for i, action in enumerate(g["actions"]):
        co = env.step(int(action)).to_core_observation()
        assert np.array_equal(co.tty_chars, g["tty_chars"][i]), f"tty mismatch @ step {i}"
        assert np.array_equal(co.message,   g["message"][i]),   f"msg mismatch @ step {i}"
    env.end()
```

- [ ] **Step 2: Run** — `pytest environments/nethack/tests/test_golden_parity.py -v`. Expected: PASS. **If FAIL, do not proceed** — diagnose buffer/encoding/action mismatch (R2/R3) before any cutover.

- [ ] **Step 3: Commit** — `git commit -m "test(engine): GATE A golden-trace parity vs nle"`.

> **[FORK] Task 8 (if GATE A fails):** reconcile obs buffer layout / action table in the fork (fork PR `F0`). Likely candidates: glyph encoding, message null-termination, action-index table. Land via PR to the fork repo, then bump the submodule pointer here.

---

## Phase 3 — NetHackCoreEnv cutover + remove nle

### Task 9: Route NetHackCoreEnv through `_engine`

**Files:**
- Modify: `environments/nethack/nethack_core/env.py:67-225`
- Test: `environments/nethack/tests/test_core_env_engine.py`

- [ ] **Step 1: Write the failing test** — `NetHackCoreEnv(task_name="NetHackScore-v0")` with `.seed(7,7); .reset()` returns a `CoreObservation`; `.step(0)` returns `(CoreObservation, float, bool, bool, dict)`; two same-seed rollouts are step-identical.

- [ ] **Step 2: Run to verify it fails** — FAIL.

- [ ] **Step 3: Reimplement env internals** — replace `gym.make`/`self._env` with a `_engine.RawEngine`; `seed()` stages `(core,disp)`; `reset()` calls `engine.start(core,disp)` (drop the seed-before-reset RuntimeError text but keep the invariant); `step()` calls `engine.step(action)`; `close()`→`engine.end()`. Keep `current_seeds`, `EpisodeMetadata`, `_hash_seeds`. Remove `import nle` / `import minihack` from `env.py:24-30`.

- [ ] **Step 4: Run to verify it passes** — PASS, incl. determinism assertion.

- [ ] **Step 5: Commit** — `git commit -m "feat(engine): NetHackCoreEnv drives _engine binding (no gym/nle)"`.

### Task 10: Update skills.py engine reads

**Files:**
- Modify: `environments/nethack/nethack_harness/tools/skills.py:617-694` (`last_observation`, `_observation_keys`, `_enum_actions_to_indices`)

- [ ] **Step 1: Write a failing test** asserting `bootstrap_character(env)` and `_enum_actions_to_indices(...)` work against the new env (no `env.underlying.unwrapped` NLE assumptions).

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Replace NLE-specific reads** — expose `engine.last_observation` and an `action_table` on `NetHackCoreEnv`; point skills.py at them instead of `env.underlying.unwrapped.last_observation` / `_observation_keys`.

- [ ] **Step 4: Run** → PASS.

- [ ] **Step 5: Commit** — `git commit -m "refactor(skills): read obs/actions from _engine, not NLE internals"`.

### Task 11: GATE A passed → remove nle (full cutover)

**Files:**
- Modify: `environments/nethack/pyproject.toml:12` (remove `nle>=1.3.0`), `:21` (remove `minihack`), `:27-29` (uv.sources minihack)
- Modify: `nethack_core/pyproject.toml`, root `pyproject.toml`/`uv.lock`

- [ ] **Step 1: Confirm GATE A green** — `pytest environments/nethack/tests/test_golden_parity.py -v` PASS.

- [ ] **Step 2: Remove deps** — delete `nle>=1.3.0` and `minihack` lines; drop the `[tool.uv.sources] minihack` block; regenerate lock (`uv lock`).

- [ ] **Step 3: Verify no residual imports** — `git grep -nE "import nle|import minihack|gym.make\(" environments/nethack` returns nothing in runtime paths.

- [ ] **Step 4: Run the env test suite** — `pytest environments/nethack/tests -q -k "engine or curriculum or core"`. Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -m "build: remove nle + minihack deps (full cutover to fork)"`.

---

## Phase 4 — GATE B snapshot spike + snapshot API

### Task 12: GATE B — multi-level snapshot-completeness spike

> **GATE B RESULT (2026-06-10, recorded during Pillar 1a):**
> **Single level = PASS (after fork fix); multi-level = FAIL → strategy "bundle level files" (Task 12b) needed for cross-level snapshots.**
>
> *What was found.* `nle_fr_snapshot` captured ctx + coroutine stack + per-env arena, but ~35 per-env heap buffers hanging off `nle_ctx_t` (player `u`, flags, dungeon topology, `gbuf` display, vision, worms, level/rooms, …) were `calloc`'d OUTSIDE the arena and the rl-port display mirror (`NetHackRL::glyphs_/chars_/colors_/…`) lives outside it too — so neither was captured. Result: restore left display/state residue across cross-branch restores.
> *Fix (fork, arena-native).* Routed those init-time buffers through a new `nle_arena_calloc()` (alloc.c) so the arena memcpy captures them by construction (matches the plan's "O(arena)" intent), dropped the now-invalid libc `free()`s in `free_nle_fields`, and added a C shim (`nle_rl_mirror_save/load`, winrl.cc) that `nle_fr_snapshot/restore` use to capture the rl mirror. **Single-level snapshot/branch is now byte-exact on glyphs/chars/colors/blstats — including repeated restores from one handle after divergent branches** (verified: `environments/nethack/tests/test_snapshot.py`).
> *Multi-level (separate, definitive from source).* Off-current dungeon levels are persisted by stock `savelev()`/`getlev()` (`src/save.c`, `src/restore.c`) to **disk files in the per-instance hackdir** (`fqn_prefix[LEVELPREFIX]`), NOT the arena. So a snapshot captures only the current level; restoring then revisiting an off-level reads the post-snapshot disk file → divergence. An empirical multi-level spike needs a deterministic descent harness (a BFS autoexplorer was prototyped but livelocks on seed 42's geometry; reaching dlvl≥2 reliably is a NetHack-bot subproject — deferred). **Conclusion stands on source inspection: do Task 12b (bundle `<hackdir>/<lock>.*` level files into the blob, or route level I/O to memfd) before relying on cross-level snapshots.**

**Files:**
- Create: `environments/nethack/tests/test_snapshot_spike.py`

- [ ] **Step 1: [FORK] expose `nle_snapshot`/`nle_restore`** thin wrappers over `nle_fr_snapshot`/`nle_fr_restore` (`src/nle_fast_reset.c`) returning/accepting an opaque handle through `nledl.h`. Open a PR to the fork repo (`liujonathan24/NetHack`); after it merges, rebuild and bump the submodule pointer here (`git add third_party/NetHack`).

- [ ] **Step 2: Write the spike test** — start, descend to dlvl 3 (step a stair-descent macro), snapshot, descend further, restore, re-descend; assert levels 1–3 `glyphs`/`chars` match the pre-restore capture.

- [ ] **Step 3: Run the spike**

Run: `pytest environments/nethack/tests/test_snapshot_spike.py -v`
- PASS → arena snapshot is complete; record in design.md §4 D3 "strategy = pure ctx+arena". Proceed to Task 13.
- FAIL → record "strategy = bundle level files"; do Task 12b before Task 13.

- [ ] **Step 4: Commit** — `git commit -m "test(engine): GATE B snapshot multi-level spike + record strategy"`.

> **[FORK] Task 12b (only if spike FAILS):** make `nle_snapshot` bundle `<hackdir>/<s_lock>.*` level files into the blob (and `nle_restore` rewrite them) OR route level I/O to memfd. Re-run Task 12 spike until PASS.

### Task 13: snapshot → bytes serialization

**Files:**
- [FORK] `src/nle_fast_reset.c` / `nledl.h`: `nle_snapshot_bytes(ctx, out_len*) -> void*`, `nle_restore_bytes(ctx, buf, len)`
- Modify: `environments/nethack/nethack_core/_engine.py`

- [ ] **Step 1: [FORK] serialize** the `{version, ctx, stack, arena[0..used]}` blob to a contiguous buffer; restore validates the version tag. Open a PR to the fork repo (`liujonathan24/NetHack`); after it merges, rebuild and bump the submodule pointer here (`git add third_party/NetHack`).

- [ ] **Step 2: Bind in `_engine`** — `RawEngine.snapshot() -> bytes`, `RawEngine.restore(b: bytes)`.

- [ ] **Step 3: Test round-trip** (`test_snapshot.py`): snapshot → step 50 → restore → next obs equals snapshot-time obs; restore cost independent of step count (compare 10 vs 5000 steps).

- [ ] **Step 4: Run** → PASS. **Commit** — `git commit -m "feat(engine): snapshot()/restore() bytes over nle_fr_snapshot"`.

### Task 14: env-level snapshot surface + replace legacy/replay internals

**Files:**
- Modify: `environments/nethack/nethack_core/env.py` (add `snapshot()/restore()`)
- Modify: `legacy/replay.py:1-78` (branch/clone via snapshot, keep `Trajectory` recording surface)

- [ ] **Step 1: Write the failing test** — `env.snapshot()`/`env.restore()` enable branching: snapshot → action A line → restore → action B line, each deterministic.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** `NetHackCoreEnv.snapshot/restore` delegating to the engine; update `legacy/replay.py` to offer snapshot-based branching while keeping `TrajectoryFrame`/`Trajectory` for the viewer.

- [ ] **Step 4: Run** → PASS. **Commit** — `git commit -m "feat(engine): env snapshot/restore + replay branching via snapshots"`.

---

## Phase 5 — nle_tune_t difficulty catalog

### Task 15: [FORK] nle_tune_t struct + get/set + binding

**Files:**
- [FORK] `src/include/nle.h` (add `nle_tune_t` sub-struct to `nle_ctx_t`), `src/nle.c`/`nledl.h` (`nle_get_tune`/`nle_set_tune`)
- Modify: `environments/nethack/nethack_core/_engine.py` (ctypes mirror + get/set)
- Create: `environments/nethack/nethack_core/tune.py` (`TuneKnobs` dataclass = the catalog)

- [ ] **Step 1: [FORK] define `nle_tune_t`** with the catalog fields (delta spec `difficulty-tuning`), defaults reproducing vanilla; add `nle_get_tune`/`nle_set_tune`. Open a PR to the fork repo (`liujonathan24/NetHack`); after it merges, rebuild and bump the submodule pointer here (`git add third_party/NetHack`).

- [ ] **Step 2: Mirror in `_engine`** — ctypes `NleTune` struct (same field order); `get_tune()->dict`, `set_tune(**knobs)`.

- [ ] **Step 3: `tune.py`** — `TuneKnobs` dataclass enumerating the catalog with defaults + `timing` metadata (R/L) so the binding can warn on mid-episode R-knob sets.

- [ ] **Step 4: Test defaults** — `tune.get()` returns all catalog knobs at vanilla defaults; a fresh game with defaults still passes GATE A parity (defaults == vanilla).

- [ ] **Step 5: Commit** — `git commit -m "feat(tune): nle_tune_t catalog struct + get/set binding + TuneKnobs"`.

### Task 16: [FORK] wire engine read-sites (per catalog)

> Each knob = one read-site. Implement in catalog order; commit per layer in the submodule and re-pin. After each, add a harness effect-test.

- [ ] **Step 1: Layer 3 live knobs first (most testable):** `dmg_to_player_scale` (`mhitu.c`), `player_hp_scale`/`hp_regen_scale` (`u.uhpmax`/regen), `vision_radius`+`fog_of_war`+`reveal_map` (`vision.c`/display), `hunger_rate_scale` (`eat.c`), `monster_difficulty_scale` (`level_difficulty()` dungeon.c). Effect-test each (e.g. `dmg_to_player_scale=0` → no HP loss; `fog_of_war=False` → level revealed).
- [ ] **Step 2: Layer 2 generation knobs:** `locked_door_rate`/`door_trap_rate`/`secret_door_rate` (`dosdoor` mklev.c), `room_density`/`room_size_scale` (`makerooms`), `corridor_connectivity` (`makecorridors`), `mob_spawn_scale`/`object_spawn_scale`/`trap_density` (populate/`makemon`/`mkobj`/`mktrap`). Test: fixed seed, lowered `locked_door_rate` → fewer D_LOCKED tiles than default.
- [ ] **Step 3: Layer 1 topology + Layer 0 start:** `max_floors`/`enabled_branches`/`floor_subset` (`init_dungeons`), `start_dlvl`/`attr_overrides`/`luck_override`/`starting_inventory` (`u_init.c`/`attrib.c`/`nle_settings.wizkit`). Test reset-time application.
- [ ] **Step 4: Commit per layer** — `git commit -m "feat(tune): wire <layer> read-sites + effect tests"`.

### Task 17: env.tune surface + R/L timing semantics

**Files:**
- Modify: `environments/nethack/nethack_core/env.py` (`self.tune` property)
- Test: `environments/nethack/tests/test_tune_timing.py`

- [ ] **Step 1: Write timing tests** — L knob (`vision_radius`) applies next step; R knob (`room_density`) set mid-game defers and warns, applies next reset.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `env.tune` exposing `get()/set()`; on R-knob mid-episode set, log a deferred-until-reset warning (per delta spec).
- [ ] **Step 4: Run** → PASS. **Commit** — `git commit -m "feat(tune): env.tune surface + R/L timing semantics"`.

---

## Phase 6 — Level customization + GameConfig

### Task 18: des-file layout loading (keep the superset)

**Files:**
- [FORK] confirm/extend runtime des load (`sp_lev.c` loader present; add a from-buffer entry if missing)
- Modify: `environments/nethack/nethack_core/_engine.py` (`load_level(des_or_path)`)
- Test: `environments/nethack/tests/test_level_custom.py`

- [ ] **Step 1: Test** — load a tiny des layout, assert the level matches (start room walls/objects present in glyphs).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** binding `load_level`; [FORK] add a des-from-buffer loader only if the existing path needs a build-time compile.
- [ ] **Step 4: Run** → PASS. **Commit** — `git commit -m "feat(level): des-file custom layout loading via _engine"`.

### Task 19: GameConfig composing all layers

**Files:**
- Create: `environments/nethack/nethack_core/game_config.py`
- Test: `environments/nethack/tests/test_game_config.py`

- [ ] **Step 1: Test** — `GameConfig(start_dlvl=2, locked_door_rate=0.0, dmg_to_player_scale=0.5, role="valkyrie")` applied to a reset produces a game honoring each field (start dlvl 2; no locked doors at seed; half damage).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `GameConfig` dataclass (start-state + topology + generation + engine knobs + optional `level_overrides` des + optional `preset_snapshot`); `NetHackCoreEnv.reset(config=...)` splits R-knobs→tune/settings pre-start, applies des/preset, then live knobs.
- [ ] **Step 4: Run** → PASS. **Commit** — `git commit -m "feat(config): GameConfig composing topology/generation/engine/start"`.

### Task 20: Migrate curriculum tiers off MiniHack

**Files:**
- Modify: `environments/nethack/nethack_harness/curriculum/curriculum.py:51-221`
- Test: `environments/nethack/tests/test_curriculum.py`

- [ ] **Step 1: Test** — each previously-MiniHack tier loads and reaches its success criterion with no `minihack` installed.
- [ ] **Step 2: Run** → FAIL (tiers still reference MiniHack des_file/`MiniHack-Skill-Custom-v0`).
- [ ] **Step 3: Re-express tiers** — replace `nle_task="MiniHack-Skill-Custom-v0"` + des_file with `GameConfig` (knobs/des/preset). Drop `des_file` MiniHack assumptions.
- [ ] **Step 4: Run** → PASS. **Commit** — `git commit -m "refactor(curriculum): tiers use GameConfig, drop MiniHack"`.

---

## Phase 7 — Test sweep + Phase 8 — Docker/docs

### Task 21: Determinism + full env suite

- [ ] **Step 1:** Add/confirm a determinism test (two same-seed rollouts step-identical for 500 steps).
- [ ] **Step 2: Run** `pytest environments/nethack/tests -q`. Expected: PASS.
- [ ] **Step 3: Commit** — `git commit -m "test(engine): determinism + full suite green"`.

### Task 22: Dockerfile.prime build path

**Files:**
- Modify: `Dockerfile.prime:21-26`

- [ ] **Step 1:** Replace the `nle` wheel build with `git submodule update --init` + `build_engine.sh`; keep cmake/bison/flex/libbz2; cache the build layer.
- [ ] **Step 2: Verify** `docker build -f Dockerfile.prime .` reaches a built `libnethack.so` (or document the build command if Docker is unavailable locally).
- [ ] **Step 3: Commit** — `git commit -m "build(docker): build fork submodule instead of nle wheel"`.

### Task 23: Docs + open-question resolutions

**Files:**
- Modify: `README.md` (engine build + submodule clone), `docs/superpowers/specs/2026-06-10-custom-nethack-engine-design.md` (record spike outcome + final API signatures)

- [ ] **Step 1:** Document `--recurse-submodules` clone, `build_engine.sh`, the `tune`/`snapshot`/`GameConfig` API, and the catalog (with timing/ranges).
- [ ] **Step 2:** Record OQ1 spike result and final C signatures in the design doc.
- [ ] **Step 3: Commit** — `git commit -m "docs(engine): build + API + catalog; record spike outcome"`.

---

## Self-Review notes

- **Spec coverage:** nethack-engine → Tasks 1–11; state-snapshot → Tasks 12–14; difficulty-tuning (catalog) → Tasks 15–17; level-customization → Tasks 18–20. tasks.md groups 1–8 map onto Phases 1–8.
- **Gates:** GATE A (Task 7) precedes nle removal (Task 11); GATE B (Task 12) precedes snapshot API finalize (Task 13–14).
- **Fork tasks** ([FORK]) are submodule commits that must be re-pinned in this repo (`git add third_party/NetHack`) as part of their step.
- **Determinism invariant** preserved throughout (`reseed=0`), asserted in Tasks 9 and 21.
