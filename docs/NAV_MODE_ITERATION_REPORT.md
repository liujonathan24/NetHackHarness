# Navigation-mode iteration report (autonomous run)

**Goal.** Validate and harden the new `move_to` (annotated plan + 3 nav modes +
A\* squeeze fix + descend-only-if-arrived) by running **one game per nav mode**,
tracing it carefully, fixing bugs found, and repeating. Cost-disciplined:
1 game × 30 turns per iteration (~$0.5). Budget tracked against the $199.52 team
wallet.

**Modes under test**
- `step_count` — walk up to `max_steps` (default 8), stop early only if a monster is on the route.
- `auto_stop` — walk until the first monster on the route.
- `preview` — return the annotated plan without moving; model commits with `max_steps`.

**What "trace carefully" checks each iteration:** does the new `move_to` feedback
render correctly? does the agent use `max_steps`/`preview`? does descent fire only
when actually on the stair? any new bug (annotation spam, monster false-positives,
coordinate mismatch, path-short handling, agent confusion)?

---

## Baseline bugs fixed before iteration 1
- **A\* diagonal squeeze** (`pathfinding.py`): A\* proposed diagonal moves between
  two walls that NetHack refuses → hero stalled one tile short → `>` pressed from
  the wrong tile → "You can't go down here." Fixed: block a diagonal when both
  orthogonal corner cells are non-walkable. Unit-tested offline.
- **Fire-and-forget descend** (`move_to`): batched `[path…, DOWN]` and never
  checked arrival. Fixed: descend only when the path genuinely ends on the target `>`.

---

## Bugs found by driving the harness myself (free, no inference)

Built a standalone driver (`/tmp/harness_play.py`) that runs the curriculum env +
code-mode `nh` namespace directly — deterministic replay from a seed, zero
inference cost. Driving seed 21 by hand immediately surfaced **four bugs**:

1. **`nh.map.rows` was never implemented (CRITICAL).** `MapView` exposed
   `.player`/`.what_is`/`.neighbors` but not `.rows` — yet every prompt tells the
   agent to read the map via `for y,row in enumerate(nh.map.rows)`. It raised
   `AttributeError` **518 times across 78 traces**; git history shows `rows` was
   *never* a MapView property. The code-mode agent could see the map in its prompt
   but could not read it programmatically — a harness-wide handicap under which the
   3/6 ceiling and 23% floor-4 rate were measured. **Fixed:** added a `rows`
   property to `MapView`.

2. **Navigation feedback was discarded in code-mode.** `nh.move_to()` returned
   `None`; the rich SkillResult feedback (where it stopped / what's ahead / the
   preview plan) never reached the agent. This silently breaks all three new nav
   modes — `preview` especially, whose entire output IS the plan. **Fixed:**
   `_dispatch` now returns the feedback and prints it for nav skills; `move_to`
   /`autoexplore` return the string.

3. **A\* diagonal squeeze** (pre-found, fixed) — proposed unexecutable diagonals
   between walls → hero stalled one tile short → `>` pressed from wrong tile.

4. **Fire-and-forget descend** (pre-found, fixed) — descended without checking
   arrival on the target `>`.

**Also confirmed NOT a bug:** on seed 21 the down-stair is genuinely unreachable
from the start pocket (46 reachable tiles; stair not connected) — the known
reachability bottleneck. `move_to`'s best-effort ("no full path; stepping toward
nearest reachable approach") handles it correctly; the agent must explore to
connect corridors before a direct path exists.

**Impact:** #1 and #2 mean prior code-mode results are not a clean measure of the
agent's ability — it was navigating half-blind (no `nh.map.rows`) and deaf (no
move_to feedback). Re-running after these fixes is the real baseline.

## Iteration 1 — 3 subagents play seed 19 (one per mode). MAJOR findings.

Instead of paid inference, spawned 3 Claude subagents to play seed 19 through the
driver (one per nav mode) and report bugs. All three got stuck on floor 1 and
independently surfaced the same critical bugs:

### CRITICAL 1 — `move_to` reports PREDICTED outcome, not ACTUAL.
Its feedback ("walked 18 steps onto the down-stairs and descended", "walked N
steps to (x,y) — reached target") is generated from the A* plan *before/without*
knowing what the engine did. When the engine stops the hero short, move_to still
claims success — even a false "descended". An agent trusting the message loops
forever. **The feedback must be a report of actual execution, not a plan.**

### CRITICAL 2 — closed doors: A* paths through them; engine won't; no way to open.
Seed 19's `>` is behind a CLOSED DOOR at (58,5). `is_walkable('+')` is true, so A*
routes through it and reports the stair reachable (my offline reachability scan was
fooled the same way — "6/12 reachable" over-counted closed-door paths). But the
engine won't step onto a closed door, so the hero stalls one tile short. There is
NO open/kick/explore primitive in the `nh` namespace, so any level with the stair
behind a closed door or fog is unwinnable. **This — not model incapacity — likely
explains much of the "reachability bottleneck" and the historical failure rate.**

### Other confirmed issues
- Over-eager monster stop: halts for monsters within 2 tiles even when off-path.
- `what_is`/`neighbors` mislabels the `x` grid-bug monster as `object [item]`.
- `move()` can be a silent no-op (blocked by wall/door) with no feedback; a single
  `move()` sometimes reports `actions_executed=2/3`.
- Sandbox strips common builtins (`repr`) with no hint; `what_is` scans can hit the
  5s code timeout.

### Fix plan (next)
1. Make `move_to` **closed-loop + honest**: step the env internally, observe after
   each step, report the ACTUAL final position/floor; descend only when genuinely
   standing on the target `>`.
2. **Door handling**: when the path hits a closed door, OPEN it as part of
   navigation (traversal, not a locating crutch) instead of stalling.
3. Tighten monster-stop to on/adjacent-to-path only; fix `x` monster typing.

## Iteration 2 — closed-loop honest move_to. Validated descents.

Rewrote move_to as **closed-loop** (steps the env itself, reports ACTUAL outcome)
and fixed the door/monster issues the play-test agents found. Fixes (all validated
on the free local driver):
- **Honest reporting** — no more predicted "walked N / descended" lies; reports the
  real final position, real descent, or the real blocker. Works in code-mode too
  (propagates pre_executed/final_obs through CodeModeResult — the skill-mode-only
  break-on-deviation no longer relied on).
- **Doors** — opens closed doors on the route; **KICKS locked doors open** (up to
  6×). A* also blocks diagonal-into/out-of-doorway (engine refuses it).
- **Monster stop** — only halts for a live, non-pet monster **on the route ahead**
  (glyphs array). Statues/objects that render as a letter no longer false-stop;
  pets ignored; **trailing** monsters behind the hero no longer halt navigation.

**Result (free driver, greedy "move_to the nearest `>`" policy):**

| seed | before (3 play-test agents) | after |
|---|---|---|
| 19 | stuck floor 1 (locked door + false success) | **descends to floor 2** |
| 20 | — | **floor 2** |
| 24 | stuck floor 1 (trailing-monster stop) | **floor 2 (1 call)** |
| 21, 22, 23 | stuck floor 1 | still floor 1 — see below |

**Remaining bug (legacy autoexplore) — gates the unreachable-stair seeds.**
Seeds 21/22/23 spawn with the `>` behind unrevealed corridors (reveal_map shows
terrain the hero has *seen*; dark corridors read as rock, so A* can't path). Those
need exploration — but **autoexplore loops**: on seed 21 it repeatedly picks
frontier (72,14), can't actually step there (blocked), and never reveals new
ground (reachable stuck at 39/40 across 15 calls). This frontier-selection loop —
not model incapacity — is why ~half the seeds were unwinnable. Fixing it is the
next high-value item (own commit; legacy `autoexplore`/`nearest_frontier`).

**Net:** the closed-loop move_to + door/monster fixes convert the *directly
navigable* seeds from stuck→descending. The autoexplore loop is the remaining
gate for the explore-required seeds.
