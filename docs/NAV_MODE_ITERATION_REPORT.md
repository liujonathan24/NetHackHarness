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
