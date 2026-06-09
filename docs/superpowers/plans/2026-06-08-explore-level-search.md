---
change: explore-level-search
design-doc: docs/netplay-vs-our-harness.md
base-ref: ef93086f79b6bbdbf9a45de1a331852b055b3af5
archived-with: 2026-06-09-explore-level-search
---

# explore-level-search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make `explore_and_descend`'s hidden-passage search COMPLETE and prioritized over a persistent per-floor map, so the agent reliably discovers downstairs hidden behind passages (today it bails early and misses them on ~60% of levels).

**Architecture:** Three focused edits to the `explore_and_descend` skill in `nethack_harness/tools/skills.py`: (1) key the persistent `search_count` by the *actual floor* (DNUM+DLEVEL) not the per-call counter, so search accumulates across calls; (2) remove the global `search_budget` early-bail — search until every candidate tile is exhausted (per-tile cap), bounded only by `max_game_steps` + the existing HP/hunger danger-halt; (3) prioritize search targets NetPlay-style (door-walled-by-stone, dead-ends, minus `search_count²`).

**Tech Stack:** Python, pytest, NLE (`blstats` indices), the existing `a_star`/`_glyph_clean_chars`.

archived-with: 2026-06-09-explore-level-search
---

## Environment & test invocation (read first)

- Working in an isolated worktree off `benchmark-netplay`.
- Tests: `cd environments/nethack && python -m pytest ../../tests/<file> -p no:cacheprovider -q --no-header`. New tests in repo-root `tests/`. Use system `python` from `environments/nethack` (the env package resolves there).
- **Known baseline: 7 pre-existing failures** (`test_rewards` + `test_integration::test_success_reward`). New tests pass in isolation; full-suite failures ⊆ those 7. Do NOT try to fix them.
- **Commit path-scoped** (`git add -- <exact files>`; never `-A`).

## Grounded facts (current code, `nethack_harness/tools/skills.py`)

- `explore_and_descend(env, obs, max_floors=1, max_game_steps=400)` at ~line 1256. It's `pre_executed` (steps the env itself, returns `SkillResult(pre_executed=True, ...)`).
- `nle_env = env.underlying.unwrapped`; `_ks = nle_env._observation_keys`; `blstats = nle_env.last_observation[_ks.index("blstats")]`.
- **blstats indices** (from `nle.nethack.NLE_BL_*`): `X=0, Y=1, HP=10, HPMAX=11, DEPTH=12, HUNGER=21, DNUM=23, DLEVEL=24`.
- Line ~1282: `search_count = getattr(nle_env, "_explore_search_count", None)` — a dict persisted on the env, currently keyed `(level_idx, x, y)`.
- Line ~1329: `def search_target(chars, start, level_idx)` — returns `((x,y), path)` or `None`.
- Lines ~1399–1400: `search_actions = 0`; `search_budget = max(120, max_game_steps // 4)`.
- Line ~1498: `if search_actions >= search_budget: break` — the early-bail.
- Lines ~1500–1514: the search block: `tgt = search_target(chars, start, level_idx)`; on `None` → `break`; else walk toward / `do(SEARCH)` x5; `search_actions += 1`; `search_count[(level_idx, tx, ty)] += 5`.
- `level_idx` is a per-call counter (0 at call start, `+= 1` on each descend within the call) — it RESETS to 0 every call, so `search_count` keyed by it mis-attributes across calls.
- Helpers available in-scope: `a_star`, `find_frontiers`, `obs_map()` (returns `(clean_chars, (x,y))`), `walk(path)` (one step), `do(action_idx)`, `SEARCH` (action index).

archived-with: 2026-06-09-explore-level-search
---

## Task 1: Key persistent search state by the actual floor

**Files:** Modify `environments/nethack/nethack_harness/tools/skills.py`.

- [ ] **Step 1: Failing test** — `tests/test_explore_search.py`

```python
import nle.nethack as N
from nethack_core.env import NetHackCoreEnv
from nethack_core.observations import shape as shape_observation
from nethack_harness.tools.skills import registry


def _floor_id(env):
    bl = env.underlying.unwrapped.last_observation[
        env.underlying.unwrapped._observation_keys.index("blstats")]
    return (int(bl[23]), int(bl[24]))  # DNUM, DLEVEL


def test_search_count_persists_per_floor_across_calls():
    e = NetHackCoreEnv(task_name="NetHackScore-v0"); e.seed(core=6, disp=6); out = e.reset()
    fid = _floor_id(e)
    # two calls on the same starting floor: search_count for that floor accumulates
    registry.call("explore_and_descend", e, shape_observation(out[0], {}), max_game_steps=120)
    sc = getattr(e.underlying.unwrapped, "_explore_search_count", {})
    keys_floor1 = [k for k in sc if k[0] == fid]
    # the persisted dict is keyed by (floor_id, x, y) — floor_id is a (dnum,dlevel) tuple
    assert all(isinstance(k[0], tuple) and len(k[0]) == 2 for k in sc), \
        "search_count must be keyed by the (dnum,dlevel) floor id, not a per-call int"
```

- [ ] **Step 2: Run → FAIL** (keys are currently `(int level_idx, x, y)`, so `k[0]` is an int).

- [ ] **Step 3: Implement.** In `explore_and_descend`, add a floor-id helper and key `search_count` by it. After the `nle_env`/`_ks` setup (near where `search_count` is fetched, ~line 1282), add:

```python
    def floor_id():
        bl = nle_env.last_observation[_ks.index("blstats")]
        return (int(bl[23]), int(bl[24]))  # (DNUM, DLEVEL) — unique per floor
```

Change the `search_target` signature + its `search_count` lookups from `level_idx` to a `floor` arg, and update the call site + the increment to pass/`use` `floor_id()`:
- `def search_target(chars, start, floor):` and inside it `search_count.get((floor, xx, yy), 0)`.
- Call site (~line 1500): `tgt = search_target(chars, start, floor_id())`.
- Increment (~line 1514): `search_count[(floor_id(), tx, ty)] = search_count.get((floor_id(), tx, ty), 0) + 5`.

(Leave the frontier `visited` set keyed by the per-call `level_idx` — re-exploring per call is cheap and correct.)

- [ ] **Step 4: Run → PASS.** `cd environments/nethack && python -m pytest ../../tests/test_explore_search.py::test_search_count_persists_per_floor_across_calls -p no:cacheprovider -q`

- [ ] **Step 5: Commit** `git add -- environments/nethack/nethack_harness/tools/skills.py tests/test_explore_search.py` — `fix(explore): key persistent search_count by actual floor (dnum,dlevel)`.

archived-with: 2026-06-09-explore-level-search
---

## Task 2: Remove the early-bail + prioritize search targets

**Files:** Modify `environments/nethack/nethack_harness/tools/skills.py`; Test `tests/test_explore_search.py`.

- [ ] **Step 1: Failing test** — add to `tests/test_explore_search.py`. It asserts the skill no longer carries a hard `search_budget` and that more seeds reach the downstairs than a tight cap would allow.

```python
import re


def _floors(feedback):
    m = re.search(r"descended (\d+) floor", feedback)
    return int(m.group(1)) if m else 0


def test_complete_search_descends_more_seeds_than_capped_baseline():
    # With a generous step budget the skill should keep searching until exhausted,
    # so across a fixed seed set MORE reach the downstairs (descend >=1 floor) than
    # the old hard ~120-action cap allowed. We assert a concrete floor here.
    descended = 0
    for seed in range(1, 9):
        e = NetHackCoreEnv(task_name="NetHackScore-v0"); e.seed(core=seed, disp=seed); out = e.reset()
        res = registry.call("explore_and_descend", e, shape_observation(out[0], {}),
                            max_floors=2, max_game_steps=1500)
        descended += 1 if _floors(res.feedback) >= 1 else 0
    # baseline (capped search) descended ~3/8; complete search should beat that.
    assert descended >= 4, f"only {descended}/8 seeds descended — search still too shallow"
```

- [ ] **Step 2: Run → FAIL or marginal** (capped search descends ~3/8).

- [ ] **Step 3: Implement.**
  (a) Delete the budget vars (~lines 1399–1400): remove `search_actions = 0` and `search_budget = max(120, max_game_steps // 4)`.
  (b) Delete the early-bail (~line 1498): remove
  ```python
        if search_actions >= search_budget:
            break  # spent our search budget — bail before starving
  ```
  (c) Delete the counter bump (~line 1513): remove `search_actions += 1`.
  (The loop is still bounded by `while state["steps"] < max_game_steps ...` and the HP/hunger danger-halt at the loop top, so it cannot run forever or starve unchecked — and the per-tile `search_count >= 12` cap inside `search_target` guarantees it returns `None` once every candidate is exhausted, which `break`s.)
  (d) Rewrite `search_target` (~line 1329) to NetPlay-style prioritization (replace the whole function body):

```python
    def search_target(chars, start, floor):
        """Best walkable tile to stand on and search for a hidden passage — NetPlay's
        compute_search_mask: a tile whose adjacent wall borders unexplored stone,
        scored by door-walled-by-stone + dead-end shape, minus search_count². Returns
        ((x,y), path) for the least-searched / most-promising / nearest tile, or None
        once every candidate has been searched to its per-tile cap (level fully searched)."""
        h, w = chars.shape
        best = None; best_key = None
        for yy in range(h):
            for xx in range(w):
                if int(chars[yy, xx]) not in (ord('.'), ord('>'), ord('<')):
                    continue  # must stand on a walkable tile
                prio = 0
                nopen = 0
                for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
                    nx, ny = xx + dx, yy + dy
                    if not (0 <= nx < w and 0 <= ny < h):
                        continue
                    nc = int(chars[ny, nx])
                    if nc in (ord('.'), ord('>'), ord('<')):
                        nopen += 1
                    elif nc == ord(' '):
                        prio += 3            # adjacent unexplored — search reveals it
                    elif nc == ord('|'):     # a wall — unexplored stone just beyond it?
                        bx, by = xx + 2 * dx, yy + 2 * dy
                        if 0 <= bx < w and 0 <= by < h and int(chars[by, bx]) == ord(' '):
                            prio += 1
                if nopen <= 1:
                    prio += 2                # dead-end: prime hidden-passage spot
                if prio == 0:
                    continue
                sc = search_count.get((floor, xx, yy), 0)
                if sc >= 12:                 # this spot is exhausted
                    continue
                p = a_star(chars, start, (xx, yy)) if (xx, yy) != start else []
                if (xx, yy) != start and not p:
                    continue
                # NetPlay: most-promising (high prio) and least-searched first, then nearest
                key = (sc * sc - prio * 100, len(p) if p else 0)
                if best_key is None or key < best_key:
                    best_key = key; best = ((xx, yy), p)
        return best
```

- [ ] **Step 4: Run → PASS.** `cd environments/nethack && python -m pytest ../../tests/test_explore_search.py -p no:cacheprovider -q`. If marginal (e.g. 4/8 vs the assert), confirm the search is exhausting candidates (not still bailing) — print the feedback for a couple seeds and check it no longer says "(hit step budget)" prematurely.

- [ ] **Step 5: Commit** `git add -- environments/nethack/nethack_harness/tools/skills.py tests/test_explore_search.py` — `feat(explore): complete prioritized hidden-passage search (no early bail)`.

archived-with: 2026-06-09-explore-level-search
---

## Task 3: Verify — descent improves, no regressions

**Files:** Test only.

- [ ] **Step 1** Run the new suite: `cd environments/nethack && python -m pytest ../../tests/test_explore_search.py -p no:cacheprovider -q --no-header` — all pass.

- [ ] **Step 2** Measure the descent lift vs baseline (informational, not an assert):

```bash
cd environments/nethack && PYTHONPATH=$PWD python -u -c "
import re
from nethack_core.env import NetHackCoreEnv
from nethack_core.observations import shape as shape_observation
from nethack_harness.tools.skills import registry
md=[]
for s in range(1,11):
    e=NetHackCoreEnv(task_name='NetHackScore-v0'); e.seed(core=s,disp=s); o=e.reset()
    r=registry.call('explore_and_descend', e, shape_observation(o[0],{}), max_floors=3, max_game_steps=1500)
    md.append(1+(int(re.search(r'descended (\d+)',r.feedback).group(1)) if re.search(r'descended (\d+)',r.feedback) else 0))
print('per-seed max_dlvl:', md, '| MEAN', round(sum(md)/len(md),2), '(was ~1.6 solo)')"
```
Expected: mean noticeably above the ~1.6 baseline (more seeds descend ≥1 floor).

- [ ] **Step 3** Full suite ⊆ baseline 7: `cd environments/nethack && python -m pytest ../../tests -p no:cacheprovider -q --no-header 2>&1 | tail -3` — failures are exactly the 7 baseline.

- [ ] **Step 4** Check off `openspec/changes/explore-level-search/tasks.md`. Commit `git add -- openspec/changes/explore-level-search/tasks.md` — `chore(comet): explore-level-search tasks complete`.

archived-with: 2026-06-09-explore-level-search
---

## Self-review

- **Coverage:** Task 1 → proposal §1.1 (per-floor keying). Task 2 → §2.1 (remove cap) + §2.2 (prioritize). Task 3 → verification (§3.1/§3.2).
- **Type consistency:** `search_target(chars, start, floor)` everywhere (signature + call site + increment all use `floor` / `floor_id()`); `search_count` keyed `(floor_id_tuple, x, y)` consistently; `floor_id()` returns `(int, int)`.
- **No placeholders:** all steps have concrete code + commands.
- **Boundedness (important):** after removing `search_budget`, the loop is still bounded by `max_game_steps` (the `while`), the HP/hunger danger-halt (returns to the LLM), and the per-tile `search_count >= 12` cap (so `search_target` eventually returns `None` → `break`). It cannot loop forever or starve unbounded.
