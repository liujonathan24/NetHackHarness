---
change: level-replay
design-doc: docs/superpowers/specs/2026-06-11-level-replay-design.md
base-ref: a8a17d9320abb3440ee2f820a5f655b75f2b352c
---

# Level-Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the NetHack-fork migration — make `EngineEnv` the sole backend (remove `nle`/`minihack`), add generate/save/load floor blobs, and snapshot-based divergent exploration.

**Architecture:** Engine C changes (level save/load, generation knobs) go to a fork branch in `third_party/NetHack` and land as a PR + submodule bump; everything else is Python in `nethack_core`/`environments/nethack`. The fork's concrete `savelev`/`getlev` levelfile is the interchange format for floors; ISAAC64 RNG reseed-after-restore drives branch exploration. Both core mechanisms were proven by spikes 0.1/0.2.

**Tech Stack:** C (NetHack 3.6 fork, ctypes), Python 3.11/3.12 (uv workspace), pytest. Linux x86-64 only.

**Two-repo rule:** Engine C → fork branch `feature/level-replay` in `third_party/NetHack`, push to the fork remote (SSH: `git@github.com:liujonathan24/NetHack.git`), open a PR. The harness only bumps the submodule pointer (`git add third_party/NetHack`) after fork commits land. NEVER commit fork C diffs into the harness repo.

**Reference:** the proven spike diff for save/load is at `docs/superpowers/spikes/2026-06-11-level-replay-spike01-savelevel.diff` (productionize it in Task A1, dropping the SPIKE/THROWAWAY framing). Build the engine with `bash nethack_core/build_engine.sh`; the `.so` is `third_party/NetHack/src/build/libnethack.so`. Run tests from repo root: `./.venv/bin/python -m pytest environments/nethack/tests/<file> -q -p no:cacheprovider`.

---

## Phase A — Fork C API (fork branch `feature/level-replay`)

All Phase A work happens inside `third_party/NetHack` on a new branch `feature/level-replay` cut from the current submodule HEAD (`feature/snapshot-tune-multilevel` @ `e1b4b7a`). Commit there; do NOT commit fork changes into the harness until Task A4.

### Task A1: `nle_save_level` / `nle_load_level` / `nle_free_blob`

**Files (fork):**
- Modify: `third_party/NetHack/src/include/nle.h` (decls, near `nle_get_seed` ~line 1165)
- Modify: `third_party/NetHack/src/src/nle.c` (impl, after `nle_get_seed` ~line 1060; add `#include <fcntl.h>` and `#include "lev.h"`)

- [ ] **Step 1: Cut the fork branch**

```bash
git -C third_party/NetHack checkout -b feature/level-replay
```

- [ ] **Step 2: Add the three functions**, productionizing the proven spike (`docs/superpowers/spikes/2026-06-11-level-replay-spike01-savelevel.diff`). Use that diff's `nle_save_level`/`nle_free_blob`/`nle_load_level` verbatim for the body, but:
  - Drop the "SPIKE (THROWAWAY)" comments; write production doc-comments.
  - Keep the **two-phase contract**: `nle_load_level` does NOT render — it ends with `vision_reset()` only. Document that the caller must `nle_step` once to re-render (rendering here jumps a dead fcontext → SIGSEGV; this is the spike's key finding).
  - In `nle_load_level`, after `getlev` + hero re-seat, also scrub the rl mirror so prior-level glyphs don't leak: call the existing rl-mirror reset used by the fast-reset path (grep `nle_rl_mirror` in `src/win/rl/winrl.cc` / `src/src/nle_fast_reset.c` for the exact symbol; if it's `nle_rl_mirror_reset()` or similar, call it; if none is callable from C here, leave a `docrt()`-on-next-step note and rely on the next step's full redraw).

Decls in `nle.h`:
```c
/* Single-level save/load. nle_save_level serializes the CURRENT dungeon
 * level to a malloc'd blob (free with nle_free_blob); nle_load_level loads
 * a blob as the current level of a started game. NOTE: load is two-phase —
 * it mutates state only; call nle_step once afterwards to re-render. */
void *nle_save_level(nle_ctx_t *, long *out_len);
void  nle_free_blob(void *blob);
int   nle_load_level(nle_ctx_t *, const void *blob, long len);
```

- [ ] **Step 3: Build the engine**

Run: `bash nethack_core/build_engine.sh`
Expected: builds `third_party/NetHack/src/build/libnethack.so` with no errors. If `lev.h`/`fcntl.h` cause redefinition warnings, confirm they're warnings not errors.

- [ ] **Step 4: Verify the symbols are exported**

Run: `nm -D third_party/NetHack/src/build/libnethack.so | grep -E "nle_save_level|nle_load_level|nle_free_blob"`
Expected: all three symbols present (T).

- [ ] **Step 5: Commit (fork repo)**

```bash
git -C third_party/NetHack add src/include/nle.h src/src/nle.c
git -C third_party/NetHack commit -m "feat(nle): nle_save_level/nle_load_level/nle_free_blob — single-level blob save/load"
```

### Task A2: Remaining generation knobs

**Files (fork):**
- Modify: `third_party/NetHack/src/include/nle.h` (the `NLE_TUNE_FIELDS(X)` X-macro, ~line 30)
- Modify: `third_party/NetHack/src/src/mklev.c` (read-sites) and any spawn site (`makemon.c`) as needed

Context: the existing `room_density` knob (see how it's wired — grep `room_density` in `src/src/mklev.c` and `nle_tuning` in the fork) is the pattern. Each knob is a `double` read via `nle_tuning.<name>` at its generation read-site. `1.0` = vanilla.

- [ ] **Step 1: Add the 5 knobs to the X-macro**

In `nle.h` `NLE_TUNE_FIELDS(X)`, add (matching the existing `X(name, default)` form — check the exact macro signature first):
```c
    X(mob_spawn, 1.0)              \
    X(trap_density, 1.0)           \
    X(locked_door, 1.0)            \
    X(corridor_connectivity, 1.0)  \
    X(room_size, 1.0)              \
```

- [ ] **Step 2: Wire each to its read-site in `mklev.c`** (and `makemon.c` for `mob_spawn`). For each, find the vanilla constant/probability and scale it by `nle_tuning.<knob>`, clamping sanely. Concretely:
  - `room_size`: in `makerooms`/`create_room` where room dimensions are chosen, scale the height/width bounds by `room_size` (clamp to engine minimums).
  - `mob_spawn`: in `makelevel`/`makemon` initial-population loop, scale the monster count.
  - `trap_density`: in `mktrap` call count / `mkroom` trap probability.
  - `locked_door`: in `dosdoor`/door-state selection, scale the locked-door probability.
  - `corridor_connectivity`: in `join`/corridor generation, scale extra-corridor probability.

  Effects are mostly off-screen; correctness here is "scales the right constant, floor still generates." (Detailed per-site code is left to the implementer reading `mklev.c`; the pattern mirrors `room_density`.)

- [ ] **Step 3: Build**

Run: `bash nethack_core/build_engine.sh`
Expected: clean build.

- [ ] **Step 4: Commit (fork repo)**

```bash
git -C third_party/NetHack add src/include/nle.h src/src/mklev.c src/src/makemon.c
git -C third_party/NetHack commit -m "feat(nle): generation knobs mob_spawn/trap_density/locked_door/corridor_connectivity/room_size"
```

### Task A3: Fork-side smoke via the binding

This task is verified after binding Task B1/B4 exist; the fork branch is otherwise ready. (No separate fork commit — covered by Task B tests.) Mark done once B-phase tests pass against this fork build.

### Task A4: Fork PR + submodule bump

- [ ] **Step 1: Push the fork branch**

```bash
git -C third_party/NetHack push -u origin feature/level-replay
```

- [ ] **Step 2: Report the PR URL** to the user (no `gh` CLI): `https://github.com/liujonathan24/NetHack/compare/feature/snapshot-tune-multilevel...feature/level-replay`. The user opens/merges it. (If the user prefers, the submodule can point at the branch tip before merge.)

- [ ] **Step 3: Bump the submodule pointer in the harness** (after the user confirms the fork branch is the intended pointer)

```bash
git add third_party/NetHack
git commit -m "build: bump NetHack submodule — level save/load + generation knobs"
```

---

## Phase B — Binding (`nethack_core/_engine.py`, `engine_env.py`)

**Files:**
- Modify: `nethack_core/_engine.py` (ctypes decls + `RawEngine` methods)
- Modify: `nethack_core/engine_env.py` (`EngineEnv` methods)
- Test: `environments/nethack/tests/test_level_blob.py` (new), `environments/nethack/tests/test_branch.py` (new)

Note: `nethack_core/` is canonical; `environments/nethack/nethack_core/` is a generated vendored copy (`tools/bundle_for_hub.py`). Edit the canonical top-level copy; re-run the bundler if the vendored copy must mirror (or note it for the cutover).

### Task B1: Bind save/load + `RawEngine.save_level`/`load_level`

- [ ] **Step 1: Write the failing test** — `environments/nethack/tests/test_level_blob.py`

```python
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "environments" / "nethack"))
from nethack_core.engine_env import EngineEnv

def test_save_load_round_trip(tmp_path):
    env = EngineEnv()
    env.reset(seeds=(42, 42))
    for _ in range(3):
        obs, _, _ = env.step(ord("."))
    saved = [r for r in obs.chars]  # grid snapshot
    blob = tmp_path / "floor.blob"
    env.save_level(blob)
    assert blob.exists() and blob.stat().st_size > 0

    env2 = EngineEnv()
    env2.reset(seeds=(1234, 1234))   # different native floor
    obs2 = env2.load_level(blob)      # returns the re-rendered obs (steps once internally)
    assert [list(r) for r in obs2.chars] == [list(r) for r in saved]
```

- [ ] **Step 2: Run it, expect failure** (`AttributeError: 'EngineEnv' object has no attribute 'save_level'`)

Run: `./.venv/bin/python -m pytest environments/nethack/tests/test_level_blob.py -q -p no:cacheprovider`

- [ ] **Step 3: Add ctypes decls in `_engine.py`** (near the other `_lib.nle_*` decls):

```python
_lib.nle_save_level.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_long)]
_lib.nle_save_level.restype = ctypes.c_void_p
_lib.nle_free_blob.argtypes = [ctypes.c_void_p]
_lib.nle_free_blob.restype = None
_lib.nle_load_level.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
_lib.nle_load_level.restype = ctypes.c_int
```

- [ ] **Step 4: Add `RawEngine.save_level`/`load_level`** (the load is two-phase — load then step once to render):

```python
def save_level(self) -> bytes:
    """Serialize the current dungeon level to a portable blob."""
    n = ctypes.c_long(0)
    ptr = _lib.nle_save_level(self._ctx, ctypes.byref(n))
    if not ptr or n.value <= 0:
        raise RuntimeError("nle_save_level failed")
    try:
        return ctypes.string_at(ptr, n.value)
    finally:
        _lib.nle_free_blob(ptr)

def load_level(self, blob: bytes) -> "RawEngine":
    """Load a level blob as the current level. Two-phase: mutates state,
    then steps once (ctrl-R = 18, no move) to re-render (rendering inside
    the C call would jump a dead fcontext)."""
    buf = ctypes.create_string_buffer(blob, len(blob))
    rc = _lib.nle_load_level(self._ctx, buf, len(blob))
    if rc != 0:
        raise RuntimeError(f"nle_load_level failed (rc={rc})")
    self.step(18)  # ctrl-R redraw inside the coroutine
    return self
```

(Use the actual ctx handle attribute name — grep `self._ctx`/`self._nle` in `_engine.py` and match it.)

- [ ] **Step 5: Add `EngineEnv.save_level(path)`/`load_level(path)`** in `engine_env.py`:

```python
def save_level(self, path) -> None:
    pathlib.Path(path).write_bytes(self.engine.save_level())

def load_level(self, path) -> CoreObservation:
    self.engine.load_level(pathlib.Path(path).read_bytes())
    return self.engine.to_core_observation()
```

(Match the existing attribute names — `self.engine`/`self._engine` and the obs builder `to_core_observation`/`_obs` — grep `engine_env.py`.)

- [ ] **Step 6: Run the test, expect PASS**

Run: `./.venv/bin/python -m pytest environments/nethack/tests/test_level_blob.py -q -p no:cacheprovider`
Expected: PASS (round-trip grid matches).

- [ ] **Step 7: Commit**

```bash
git add nethack_core/_engine.py nethack_core/engine_env.py environments/nethack/tests/test_level_blob.py
git commit -m "feat(engine): bind nle_save_level/load_level; EngineEnv.save_level/load_level (two-phase render)"
```

### Task B2: Generate-N-floors smoke + floor-library helper

- [ ] **Step 1: Add the test** to `test_level_blob.py`:

```python
def test_generate_and_save_many(tmp_path):
    saved = []
    for seed in (1, 2, 3, 4, 5):
        env = EngineEnv()
        env.reset(seeds=(seed, seed))
        env.step(ord("."))
        p = tmp_path / f"floor_{seed}.blob"
        env.save_level(p)
        saved.append(p.read_bytes())
    assert all(s for s in saved)
    assert len({bytes(s) for s in saved}) >= 4  # floors differ across seeds
```

- [ ] **Step 2: Run, expect PASS**

Run: `./.venv/bin/python -m pytest environments/nethack/tests/test_level_blob.py::test_generate_and_save_many -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add environments/nethack/tests/test_level_blob.py
git commit -m "test(engine): generate-and-save N distinct floors"
```

### Task B3: `RawEngine.reseed` + `EngineEnv.branch`

`nle_set_seed` is already exported (Spike 0.2). Bind it and build `branch`.

- [ ] **Step 1: Write the failing test** — `environments/nethack/tests/test_branch.py`

```python
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "environments" / "nethack"))
from nethack_core.engine_env import EngineEnv

def _trace(env, steps):
    out = []
    for _ in range(steps):
        obs, _, _ = env.step(ord("s"))  # search: random-ish outcomes
        out.append(b"".join(bytes(r) for r in obs.chars))
    return out

def test_branch_diverges_with_reseed():
    env = EngineEnv(); env.reset(seeds=(42, 42))
    for _ in range(8):
        env.step(ord("s"))
    branches = env.branch(8, reseed=True, horizon=40)
    # branches is a list of per-branch traces; reseeded branches should not all be identical
    assert len({tuple(b) for b in branches}) >= 2

def test_branch_identical_without_reseed():
    env = EngineEnv(); env.reset(seeds=(42, 42))
    for _ in range(8):
        env.step(ord("s"))
    branches = env.branch(4, reseed=False, horizon=40)
    assert len({tuple(b) for b in branches}) == 1  # no reseed -> identical
```

- [ ] **Step 2: Run, expect failure** (`branch` missing)

- [ ] **Step 3: Bind `nle_set_seed` in `_engine.py`** (if not already) and add `RawEngine.reseed`:

```python
_lib.nle_set_seed.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_char]
_lib.nle_set_seed.restype = None

def reseed(self, core: int, disp: int) -> "RawEngine":
    _lib.nle_set_seed(self._ctx, ctypes.c_ulong(core), ctypes.c_ulong(disp), b"\x00")
    return self
```

- [ ] **Step 4: Add `EngineEnv.branch`** in `engine_env.py` (snapshot → for each branch: restore → reseed(distinct) → run horizon, collecting a per-step trace; the reseed comes AFTER restore, per Spike 0.2):

```python
def branch(self, n: int, reseed: bool = True, horizon: int = 40, action: int = ord("s")):
    """Return n continuations from the current state. With reseed=True each
    branch reseeds the RNG after restore so random-chance events diverge."""
    handle = self.snapshot()
    results = []
    for i in range(n):
        self.restore(handle)
        if reseed:
            self.engine.reseed(core=1000 + i, disp=2000 + i)
        trace = []
        for _ in range(horizon):
            obs, _, _ = self.step(action)
            trace.append(b"".join(bytes(r) for r in obs.chars))
        results.append(trace)
    return results
```

(Match `snapshot()`/`restore()` signatures already on `EngineEnv` — grep `engine_env.py:115`.)

- [ ] **Step 5: Run the tests, expect PASS**

Run: `./.venv/bin/python -m pytest environments/nethack/tests/test_branch.py -q -p no:cacheprovider`
Expected: both PASS (reseed diverges; no-reseed identical).

- [ ] **Step 6: Commit**

```bash
git add nethack_core/_engine.py nethack_core/engine_env.py environments/nethack/tests/test_branch.py
git commit -m "feat(engine): RawEngine.reseed + EngineEnv.branch(n, reseed) divergent exploration"
```

### Task B4: New generation knobs settable + safe

- [ ] **Step 1: Add the test** — `environments/nethack/tests/test_generation.py` already exists; add:

```python
NEW_KNOBS = ["mob_spawn", "trap_density", "locked_door", "corridor_connectivity", "room_size"]

def test_new_generation_knobs_settable_and_safe():
    for knob in NEW_KNOBS:
        for val in (0.0, 0.5, 1.0, 1.5):
            env = EngineEnv()
            env.reset(seeds=(42, 42), tune={knob: val})  # tune-at-start
            obs, _, _ = env.step(ord("."))
            assert obs is not None  # floor generated, no crash
            assert env.get_tune()[knob] == val  # round-trips
```

- [ ] **Step 2: Run, expect PASS** (knobs are generic via the catalog once the fork build from A2 is in place)

Run: `./.venv/bin/python -m pytest environments/nethack/tests/test_generation.py::test_new_generation_knobs_settable_and_safe -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add environments/nethack/tests/test_generation.py
git commit -m "test(engine): new generation knobs settable + safe at start"
```

---

## Phase C — Make `EngineEnv` canonical

**Files:**
- Modify: `nethack_core/env.py` (`NetHackCoreEnv` delegates to `EngineEnv`; remove the `import nle`/`import minihack` lines in a later cutover task, but rewire seed/reset/step now)
- Modify: `nethack_core/skills.py` (action mapping + observation reads)
- Test: `environments/nethack/tests/test_core_env_parity.py` (new)

### Task C1: `NetHackCoreEnv` delegates to `EngineEnv`

- [ ] **Step 1: Read `nethack_core/env.py`** end-to-end to map the public surface (`seed`, `reset`, `step`, `_observation_keys`, `last_observation`, the `CoreObservation` build, `des_file`/`task_name` handling). Note every attribute consumers read.

- [ ] **Step 2: Write the parity test** — `environments/nethack/tests/test_core_env_parity.py`:

```python
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "environments" / "nethack"))
from nethack_core.env import NetHackCoreEnv
from nethack_core.observations import StructuredObservation  # adjust import to actual

def test_core_env_steps_via_engine():
    env = NetHackCoreEnv(task_name="NetHackScore-v0")
    env.seed(42, 42)
    obs = env.reset()
    obs2, reward, terminated, truncated, info = env.step(ord("."))
    # structured fields present + shaped as before
    assert obs2.chars.shape == (21, 79)
    assert obs2.blstats is not None
```

- [ ] **Step 3: Rewire `NetHackCoreEnv.seed/reset/step`** to construct and drive an internal `EngineEnv`, building `CoreObservation` from the binding buffers exactly as `EngineEnv` already does (reuse `EngineEnv.to_core_observation`/the obs builder). Keep `task_name` handling: native tasks (`NetHackScore-v0`, `NetHackChallenge-v0`) → plain generation; `des_file`/curriculum tiers → `EngineEnv.load_level(blob)` (wired fully in Phase E — for now, accept a `level_blob` path param and load it). Preserve `_observation_keys`, `last_observation`, and the return tuple shape `(obs, reward, terminated, truncated, info)`.

(This is the largest single task. If it exceeds ~200 lines, split: C1a = seed/reset/step happy path on native tasks; C1b = level_blob path + info/reward/termination parity.)

- [ ] **Step 4: Run the parity test, expect PASS**

Run: `./.venv/bin/python -m pytest environments/nethack/tests/test_core_env_parity.py -q -p no:cacheprovider`

- [ ] **Step 5: Commit**

```bash
git add nethack_core/env.py environments/nethack/tests/test_core_env_parity.py
git commit -m "feat(env): NetHackCoreEnv drives EngineEnv (binding-backed seed/reset/step)"
```

### Task C2: `StructuredObservation` field/type parity

- [ ] **Step 1: Add a parity assertion test** comparing the post-rewire observation's field names/dtypes/shapes against the documented contract in `nethack_core/observations.py` `shape()`:

```python
def test_structured_observation_parity():
    env = NetHackCoreEnv(task_name="NetHackScore-v0"); env.seed(42, 42); env.reset()
    obs, *_ = env.step(ord("."))
    from nethack_core import observations
    for field, spec in observations.shape().items():   # adjust to actual API
        val = getattr(obs, field)
        assert val.shape == spec.shape and val.dtype == spec.dtype
```

- [ ] **Step 2: Run, fix any drift in the obs builder until PASS.** Commit.

```bash
git add environments/nethack/tests/test_core_env_parity.py nethack_core/observations.py
git commit -m "test(env): StructuredObservation field/type parity across the engine cutover"
```

### Task C3: `skills.py` action mapping + observation reads

- [ ] **Step 1: Grep `skills.py`** for `last_observation`, `_observation_keys`, and any `nle`-specific action constants. List each read.
- [ ] **Step 2: Update** the action-index mapping to the engine's keypress action space (ASCII; GATE A already validated identity) and point `last_observation` reads at the binding-backed obs. Run the existing skills tests.

Run: `./.venv/bin/python -m pytest environments/nethack/tests/ -q -p no:cacheprovider -k skill`
Expected: green (or add a smoke test if none exists).

- [ ] **Step 3: Commit**

```bash
git add nethack_core/skills.py
git commit -m "feat(skills): action mapping + observation reads via the binding"
```

### Task C4: snapshot/restore/tune surface on `NetHackCoreEnv`

- [ ] **Step 1: Add `snapshot()`/`restore()`/`save_level()`/`load_level()`/`branch()` + a `tune` surface** to `NetHackCoreEnv` that delegate to the internal `EngineEnv`. Add a test asserting `snapshot()`→`restore()` round-trips and `tune.set(...)` round-trips on `NetHackCoreEnv`.
- [ ] **Step 2: Run, PASS, commit.**

```bash
git add nethack_core/env.py environments/nethack/tests/test_core_env_parity.py
git commit -m "feat(env): snapshot/restore/tune/branch surface on NetHackCoreEnv (delegated)"
```

---

## Phase D — Snapshot + explore (replace `legacy/replay.py` re-execution)

**Files:**
- Modify: `legacy/replay.py`
- Modify: `tests/test_replay.py`, `tools/record_demo.py`

### Task D1: Swap `legacy/replay.py` to snapshot/restore

- [ ] **Step 1: Read `legacy/replay.py`** — note `TrajectoryRecorder`, `TrajectoryFrame`, the `(seeds, action_sequence)` reconstruct path, and what `tests/test_replay.py` + `tools/record_demo.py` consume.
- [ ] **Step 2: Replace the re-execution internals**: the recorder keeps storing frames (viewer-readable, unchanged), but the reconstruct/clone path uses `env.snapshot()`/`env.restore()` against the binding-backed env. Keep the public `TrajectoryRecorder` API and the stored `.ndjson`/frame format byte-compatible so the replay viewer is unaffected (old recordings stay readable; no migration).
- [ ] **Step 3: Update `tests/test_replay.py`** to the snapshot mechanism; keep an assertion that an old-format recording still loads into the viewer surface.

Run: `./.venv/bin/python -m pytest tests/test_replay.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 4: Update `tools/record_demo.py`** to the new recorder path; smoke it.

Run: `./.venv/bin/python tools/record_demo.py --help` (and a short record if it has a quick mode)

- [ ] **Step 5: Commit**

```bash
git add legacy/replay.py tests/test_replay.py tools/record_demo.py
git commit -m "refactor(replay): snapshot/restore reconstruct; frames stay viewer-readable"
```

---

## Phase E — Curriculum migration (drop MiniHack)

**Files:**
- Create: `nethack_core/levels/build_curriculum_blobs.py` (offline compiler), `nethack_core/levels/*.blob` (generated assets)
- Modify: `environments/nethack/nethack_harness/curriculum/curriculum.py`
- Test: `environments/nethack/tests/test_curriculum_blobs.py` (new)

### Task E1: Compile the 3 static des tiers to level blobs

The 3 inline-des tiers are `empty_room`, `solo_combat`, `multi_combat` (`curriculum.py:63,84,107`). Compile each once via `lev_comp` → instantiate → `EngineEnv.save_level`.

- [ ] **Step 1: Write `nethack_core/levels/build_curriculum_blobs.py`** — for each tier des string: write to a temp `.des`, run the fork's `lev_comp` (`third_party/NetHack/src/util/lev_comp`, built by `build_engine.sh`; build it if absent with `make -C third_party/NetHack/src/build lev_comp`) to produce a `.lev`; load that `.lev` into a fresh `EngineEnv` as the starting special level; `save_level` to `nethack_core/levels/<tier>.blob`. (If loading a `lev_comp` template needs a distinct entry from `load_level` of a concrete blob, capture the concrete level right after instantiation and save THAT — the design's "instantiate once then save concrete" step.)
- [ ] **Step 2: Run it**, producing `nethack_core/levels/{empty_room,solo_combat,multi_combat}.blob`.

Run: `./.venv/bin/python nethack_core/levels/build_curriculum_blobs.py`
Expected: 3 `.blob` files written.

- [ ] **Step 3: Commit** (blobs are checked-in assets — they're small)

```bash
git add nethack_core/levels/
git commit -m "feat(curriculum): compile static des tiers to level blobs (offline)"
```

### Task E2: `curriculum.py` loads blobs instead of MiniHack

- [ ] **Step 1: Change `TierSpec`** so the 3 static tiers reference a `level_blob` path (`nethack_core/levels/<tier>.blob`) instead of `nle_task="MiniHack-Skill-Custom-v0"` + `des_file`. The native tiers (`des_file=None`) keep using native generation.
- [ ] **Step 2: Update the tier→env construction** so `level_blob` tiers build `NetHackCoreEnv` with the blob passed to the `level_blob` load path (Task C1), and native tiers build normally. Remove the `MiniHack-Skill-Custom-v0` / `des_file` make_kwargs path.

- [ ] **Step 3: Commit**

```bash
git add environments/nethack/nethack_harness/curriculum/curriculum.py nethack_core/env.py
git commit -m "feat(curriculum): load static tiers from level blobs (no MiniHack env)"
```

### Task E3: Behavioral-smoke parity (minihack uninstalled)

- [ ] **Step 1: Write `environments/nethack/tests/test_curriculum_blobs.py`**:

```python
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "environments" / "nethack"))
from nethack_harness.curriculum.curriculum import TIERS, make_tier_env  # adjust to actual factory

def test_static_tiers_load_and_have_downstair():
    for name in ("empty_room", "solo_combat", "multi_combat"):
        env = make_tier_env(name); env.seed(42, 42); obs = env.reset()
        grid = "\n".join("".join(chr(c) for c in row) for row in obs.chars)
        assert ">" in grid  # downstair present
        for _ in range(5):  # short rollout runs
            obs, *_ = env.step(ord("."))
        assert obs is not None
```

- [ ] **Step 2: Run with minihack importable still — PASS. Then confirm it does not import minihack** (grep the import graph; the test must not transitively import `minihack`).

Run: `./.venv/bin/python -m pytest environments/nethack/tests/test_curriculum_blobs.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add environments/nethack/tests/test_curriculum_blobs.py
git commit -m "test(curriculum): static tiers load + play without MiniHack (behavioral smoke)"
```

### Task E4: Drop the `minihack` dependency

- [ ] **Step 1: Remove `minihack`** from `nethack_core/pyproject.toml` (the `"minihack @ git+..."` line) and any `[project.optional-dependencies]` extra; remove `import minihack` from `nethack_core/env.py` and the MiniHack-not-installed error branch.
- [ ] **Step 2: `uv sync`** at repo root; confirm it resolves without minihack.

Run: `/scratch/gpfs/ZHUANGL/jl0796/bin/uv sync`
Expected: resolves clean.

- [ ] **Step 3: Commit**

```bash
git add nethack_core/pyproject.toml nethack_core/env.py uv.lock
git commit -m "build: drop the minihack dependency (curriculum runs on level blobs)"
```

---

## Phase F — The nle cutover

**Files:** `nethack_core/env.py`, `nethack_core/__init__.py`, `nethack_core/pyproject.toml`, `uv.lock`, `Dockerfile.prime`, `environments/nethack/nethack_harness/prompt/image_render.py`

### Task F1: Remove `import nle`

- [ ] **Step 1: Delete the `import nle` line** in `nethack_core/env.py:25` and any nle-gym registration reliance. Ensure `NetHackCoreEnv` no longer calls `gym.make(nle_task)` for native tasks — native generation now goes through `EngineEnv` directly (wire native `task_name` → `EngineEnv.reset()` with the appropriate defaults). Remove nle from `nethack_core/__init__.py`'s eager-import path if present.
- [ ] **Step 2: Run the full engine suite — PASS.**

Run: `./.venv/bin/python -m pytest environments/nethack/tests/ -q -p no:cacheprovider`

- [ ] **Step 3: Commit**

```bash
git add nethack_core/env.py nethack_core/__init__.py
git commit -m "refactor(env): remove the nle import path — EngineEnv is the sole backend"
```

### Task F2: Drop `nle` from deps + grep acceptance

- [ ] **Step 1: Remove `"nle>=1.3.0"`** from `nethack_core/pyproject.toml` (and any other pyproject/lock referencing it). `uv sync`.

Run: `/scratch/gpfs/ZHUANGL/jl0796/bin/uv sync`
Expected: resolves without nle.

- [ ] **Step 2: Acceptance grep — must be clean** (outside archived/legacy docs + the vendored copy if it still mirrors):

Run: `grep -rn "import nle\|from nle\|minihack" --include=*.py nethack_core/ environments/nethack/nethack_harness/ tools/ tests/ | grep -v __pycache__`
Expected: no live hits (only comments/docstrings acceptable; ideally none).

- [ ] **Step 3: Commit**

```bash
git add nethack_core/pyproject.toml uv.lock
git commit -m "build: remove the nle>=1.3.0 dependency — fork engine is the sole backend"
```

### Task F3: `Dockerfile.prime` builds the submodule

- [ ] **Step 1: Rewrite `Dockerfile.prime`** to `git submodule update --init --recursive` + `bash nethack_core/build_engine.sh` (system deps cmake/bison/flex already present per the existing file) instead of `pip install nle`. Keep the build-cache layering.
- [ ] **Step 2: Lint/validate** the Dockerfile builds the engine step (a full image build may be out of scope on this node — at minimum `docker build --check` or a careful review; note if a full build can't run here).
- [ ] **Step 3: Commit**

```bash
git add Dockerfile.prime
git commit -m "build: Dockerfile.prime builds the NetHack submodule instead of the nle wheel"
```

### Task F4: Tileset for `image_render.py`

- [ ] **Step 1: Read `environments/nethack/nethack_harness/prompt/image_render.py`** — it uses MiniHack's `GlyphMapper` tiles, with a `NETHACK_TILESET` override. Replace the MiniHack tile source: bundle a tileset file (e.g. vendor `nethack_core/assets/tiles.npy` or a BMP the renderer can read) and default to it; keep `NETHACK_TILESET` override. Make the `minihack` import path fully removable.
- [ ] **Step 2: Smoke** the renderer produces a PNG without minihack.

Run: `./.venv/bin/python -c "from nethack_harness.prompt.image_render import glyphs_to_png_b64; print('ok')"` (from `environments/nethack`)
Expected: imports + runs without minihack.

- [ ] **Step 3: Commit**

```bash
git add environments/nethack/nethack_harness/prompt/image_render.py nethack_core/assets/
git commit -m "feat(render): bundle a tileset; drop the MiniHack GlyphMapper dependency"
```

---

## Phase G — Verify + docs

### Task G1: Parity + determinism stay green

- [ ] **Step 1: Run GATE A parity + determinism + the full engine suite.**

Run: `./.venv/bin/python -m pytest environments/nethack/tests/ -q -p no:cacheprovider`
Expected: all green (test_golden_parity, test_snapshot, test_engine_env, test_level_blob, test_branch, test_generation, test_curriculum_blobs, …).

- [ ] **Step 2: Re-bundle the vendored copy** if `environments/nethack/nethack_core/` must mirror the canonical engine changes: `./.venv/bin/python tools/bundle_for_hub.py` (confirm it copies the new `_engine.py`/`engine_env.py`/`env.py`/`levels/`). Commit any mirror update.

```bash
git add environments/nethack/nethack_core/ && git commit -m "build: re-bundle vendored nethack_core mirror" || echo "no mirror change"
```

### Task G2: Full eval smoke end-to-end

- [ ] **Step 1: Run one short eval rollout** through the new engine (find the eval entrypoint — grep for the rollout/eval runner under `environments/nethack`; e.g. a `verifiers`/`vf-eval` harness or `tools/`). Run the smallest end-to-end rollout (1 episode, few steps) and confirm it completes with the fork engine and no `nle` import.

Run: (the project's minimal eval command — document the exact one used)
Expected: completes, produces a trace, no nle.

- [ ] **Step 2: Commit** any fixups needed for the eval path.

### Task G3: Docs + supersede the parent change

- [ ] **Step 1: Write engine-layer docs** (`environments/nethack/README.md` or `docs/`): the binding, snapshot/branch API, the tune knobs (ranges + start-vs-live timing), the level-blob format + floor library, and the `--recurse-submodules` clone + `build_engine.sh` steps. Remove MiniHack/nle install instructions.
- [ ] **Step 2: Record OQ resolutions** (OQ4 = concrete savelev/getlev blobs; final `nle_save_level`/`nle_load_level`/`reseed`/`branch` signatures) in the design doc's "Open items resolved" section.
- [ ] **Step 3: Mark the absorbed `custom-nethack-engine` tasks as superseded by `level-replay`** in `openspec/changes/custom-nethack-engine/tasks.md` (add a header note; the change can then be archived separately).
- [ ] **Step 4: Commit**

```bash
git add environments/nethack/README.md docs/ openspec/changes/custom-nethack-engine/tasks.md
git commit -m "docs(level-replay): engine layer, snapshot/branch, level blobs; supersede parent tasks"
```

---

## Self-review notes (coverage map)

- proposal "What Changes" → A1/B1/B2 (save/load), A2/B4 (knobs), C1-C4 (EngineEnv canonical), B3/D1 (snapshot+explore), E1-E4 (curriculum off MiniHack), F1-F4 (cutover), G1-G3 (verify/docs).
- delta spec `nethack-engine` (sole backend; branch) → C1/F1/F2 + B3. `level-customization` (generate/save/load; curriculum no-minihack) → B1/B2/E1-E4. `difficulty-tuning` (new knobs) → A2/B4.
- Hard gates: G1 keeps GATE A parity + determinism green across the cutover.
- Two-repo rule: all C in Phase A on the fork branch; harness bump in A4.
