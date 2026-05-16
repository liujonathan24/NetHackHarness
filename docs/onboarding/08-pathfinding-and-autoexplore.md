# Pathfinding: `move_to` and `autoexplore`

**Status:** Shipped in `nethack_core/pathfinding.py` + skills in
`nethack_core/skills.py` as of Day 3. Tested in `tests/test_pathfinding.py`.

## Why this is the biggest agent-UX win in the package

Without `move_to`, the model has to pick a compass direction once per turn.
NetHack maps are 21x79 — a typical "go to the stairs" sequence is 15+ moves.
That's 15 LM-turns spent on navigation alone, with the model regenerating
context every time. Even with our restricted action set, the policy spends
most of its tokens deciding *"E" vs "SE"*.

`move_to(x, y)` and `autoexplore()` collapse navigation to one tool call.
The agent says *"go to (40, 12)"* or *"explore"* and the harness emits the
action sequence under the hood. The model only re-enters the loop when
something interesting happens (a monster, a menu, a death). NetPlay (Jeurissen
et al., 2024) and glyphbox (Jan 2026) both reported this as the single
largest improvement in their tool surface.

## The architecture

Two modules:

```
nethack_core/pathfinding.py     # algorithms (pure, no NLE state)
nethack_core/skills.py          # @registry.register("move_to") + ("autoexplore")
```

The split matters: `pathfinding.py` is testable with numpy arrays alone (no
NLE rollouts), so the test suite runs in milliseconds. The skill wrappers
that touch `env.underlying` are thin.

### A* (`pathfinding.a_star`)

8-connected grid with Chebyshev heuristic. Open set is a `heapq` sorted by
`f_score = g + h`. Standard textbook. Cost = 1 per step, including
diagonals — NetHack permits 8-direction movement at the same time cost.

### Walkability (`pathfinding.is_walkable`)

A frozenset of ASCII byte values that count as walkable tiles. Includes
floor (`.`), corridor (`#`), stairs (`<`, `>`), altars, fountains, thrones,
open doors (`'`), closed doors (`+` — we'll try; locked is a no-op), and
all the items-on-floor glyphs (`$`, `(`, `[`, `*`, etc.).

NOT walkable: walls (`|`, `-`), unseen / rock (` `), the player tile itself
(`@`). The last one matters: A* refuses to plan a path that *passes through*
the player's current tile via a self-loop, but we special-case `start ==
goal` so "stay" is a valid 0-step path.

### Doorway-corner blocking

NetHack forbids diagonal movement that "clips" a doorway. If the player
stands NW of a door, they can't step SE diagonally — they have to step S
then E (or E then S). `a_star` checks: for any diagonal step `(dx, dy)`, the
two orthogonal-adjacent tiles must NOT be doors. Without this, the
pathfinder would propose a diagonal the game silently refuses, and the
agent would bounce in place.

### Frontier discovery (`pathfinding.find_frontiers`)

A frontier is a *walkable tile adjacent to an unseen tile*. Unseen
renders as space (`' '`). So we scan every tile, check if it's walkable,
then check if any of its 8 neighbors is space. O(h * w) — fine for a
21x79 grid.

### `nearest_frontier`

BFS from the player position. First time we hit a tile that's also in the
frontier set, we return `(target, path)`. BFS guarantees shortest-path-in-
steps (each step is 1 cost). The alternative (A* to each frontier and pick
the cheapest) would be slower. None returned means the level is fully
explored — caller should `descend` or `move_to(<stair>)`.

## Skill API

```python
move_to(x: int, y: int)            # A* to (x, y); fail if no path
autoexplore(max_steps: int = 30)   # walk one trip to nearest frontier
```

Both return `SkillResult(actions=[...], feedback=...)`. The harness steps
through `actions` serially, accumulating scout + descent reward as it goes,
and bails if `terminated or truncated`. So if a monster appears mid-trip
and kills the player, the harness handles the death naturally — no need
for special "interruption" plumbing in the skill itself.

`autoexplore` caps its action list at `max_steps` (default 30) so the agent
gets re-prompted reasonably often. Smaller `max_steps` = more
chances-to-react; larger = fewer LM turns per level. 30 is a sweet spot
on small dungeons; tune as we get more data.

## What we deliberately *don't* do

- **Belief-state pathing.** A* operates on the *currently visible* map.
  Tiles that have been seen and then walked off of are still tracked
  (NetHack renders them dim, we still get them in `chars`). Tiles that are
  *behind* unseen regions are unknown — we can't path to them yet.
- **Run-mode.** Many NetHack roguelikes have a "G" prefix for "run until
  something interesting." We could expose this as one or two raw actions,
  but the run mode interacts badly with our seed-deterministic stepping
  (it consumes a variable number of in-game turns per action). Sticking
  with per-tile steps keeps the trajectory replay clean.
- **Lock-picking on closed doors.** `+` is walkable in our model; if the
  door is locked, the underlying NLE step is a no-op and we proceed. A
  smarter version would detect locked-door messages and emit `#force` or
  similar. Future work.

## Determinism

Both A* and BFS visit nodes in a deterministic order (heapq breaks ties
with a monotonic counter; BFS uses FIFO). Given the same map, both
functions produce the same path. The `move_to` / `autoexplore` skills are
thus replay-safe — the same seed + same skill calls produce the same
trajectory.

## How to verify

```bash
uv run pytest tests/test_pathfinding.py -v
```

15 tests cover:
- Walkability of each tile class.
- A* on straight, diagonal, walled, and doorway-corner cases.
- Start-equals-goal edge case.
- Frontier discovery with fully-explored vs partially-explored grids.
- `nearest_frontier` returning the closest reachable frontier.

End-to-end (live NLE; requires the venv installed):

```bash
source .venv/bin/activate
python -c "
from nethack_core.env import NetHackCoreEnv
from nethack_core.skills import autoexplore
env = NetHackCoreEnv(task_name='NetHackScore-v0')
env.seed(core=42, disp=42); env.reset()
r = autoexplore(env, None, max_steps=10)
print('action_count:', len(r.actions), 'feedback:', r.feedback)
"
```

## Future work

- **Multi-level pathing.** Add `move_to_level(dlvl)` that paths to the
  appropriate stair, descends, then continues. Needs a `dosave`-aware
  level-cache to be useful across episodes.
- **Hazard avoidance.** Currently A* treats lava (`}` water-pool variant),
  traps (we don't see traps until triggered), and items pinned to the
  floor (cursed) as walkable. A hazard layer + per-tile costs would let
  the model say *"path to (x, y), avoid traps"*.
- **Interrupt-on-monster autoexplore.** The current `autoexplore` returns
  the precomputed path. If a monster appears mid-trip the harness *does*
  break on terminated/truncated, but a less catastrophic version would
  notice a new hostile glyph in obs.chars between steps and return early.
  That requires the skill to do its own stepping (see the design comment
  in `skills.py`).
- **Glyph-based walkability.** Using `obs.glyphs` instead of `obs.chars`
  would let us distinguish "an Elbereth-engraved floor" (don't step off!)
  from "regular floor." Worth the version-lock cost if/when we want this
  level of sophistication.
