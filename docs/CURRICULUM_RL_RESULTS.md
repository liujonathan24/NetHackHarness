# Curriculum RL experiments — Go-Explore & Voyager (real primitives only)

**Faithful setup (the key constraint).** The agent gets **no descend/ascend
skill and no auto-descend**. It plays a female-neutral Valkyrie with **full
vision** (`reveal_map=1.0`, no fog of war — secret corridors/doors are revealed
too) and may only use real game commands. The cross-branch jump
(Dungeons-of-Doom 3 ↔ Gehennom 48) is **internal** — it fires only when the hero
genuinely stands on the boundary stair (`nle_hero_on_stair`) and takes the real
`>`/`<`. So the agent must *find and reach* the stairs itself; nothing hands it a
descent.

Curriculum = a 6-floor down / 6-floor up tour:

```
floor:   1     2     3            4      5      6
level:  DoD1  DoD2  DoD3  --jump--> Geh48  Geh49  Geh50    (then climb back up)
```

Metric: deepest curriculum floor reached (1–6) and floors climbed back, over time.

## In-spirit rule: the developer does not solve navigation

The earlier iteration of this experiment baked navigation help into the tooling:
`move_to` opened/kicked doors, attacked monsters, and best-effort-pushed through
blockers. That is the *developer* solving the level, not the algorithm — "not in
the spirit." This version strips all of that. The agent's primitives are now:

- `move_to(x,y)` — **generic** A* over visibly-open terrain only (floor,
  corridor, open door, doorway, stairs, items). It walks as far toward the goal
  as open ground allows, then **stops and factually reports the blocker** (a
  closed door / a monster + direction). It does *not* open, kick, attack, or
  push.
- `move(dir)` — a single step (into a monster = attack/swap; into a door = bump).
- `open(dir)` / `kick(dir)` — open or kick-down a door (the agent's decision).
- `search` — search for hidden passages.
- `>` / `<` — take stairs (only act when the hero is on a stair tile).

So **all navigation intelligence — routing across rooms, deciding to open vs.
kick a door, fighting vs. swapping past a monster — must come from the agent**
(the LLM, or Go-Explore's search), never from hand-written tool logic. Go-Explore
likewise no longer force-takes a stair it lands on; it samples primitives
(compass moves, run-macros, `search`, `>`/`<`) from a weighted set and must
*discover* descent.

## Results

| method | agent | deepest floor / 6 | climbed back | seeds |
|---|---|---|---|---|
| **Go-Explore** | random primitives (weighted compass/run/search/`>`/`<`; no forced stair) | **2** (seed 19); **1** (seeds 2, 9) | 0 | 19, 2, 9 (600 iters) |
| **Voyager** | GLM 5.2, full vision, generic `move_to` + `open`/`kick`/`move`/`search` + `>`/`<` | **1** (all seeds) | 0 | 19, 2, 9 (45 turns each) |

Voyager seed 19 (in-spirit): 45 turns, **never left floor 1** — a genuine mix of
22 `move_to`, ~18 `move` (attacking/bumping blockers), 5 `search`. The LLM *did*
reason about blockers and act on them; it just never chained the moves into a
route that reached the downstair.

## Is it the tooling or the agent? (diagnostic proof)

We verified the floor-1 result is a real *agent* limitation, not a broken
primitive, on seed 19 / DoD1 (hero starts at (66,7); the downstair is at
(50,16)):

- **The downstair tile is walkable** in the walkview (`is_walkable('>') = True`);
  `move_to` and the frontier-walk are mechanically correct (no coordinate-
  transpose or LUT bug).
- **From the start, the reachable open area is just the starting room** (61
  tiles). Every exit is a **closed door** (`+`), which `move_to` correctly treats
  as non-walkable — opening it is the agent's call.
- **If every closed door is opened, the stair becomes reachable** (230 tiles
  reachable; `a_star` path length 19, through ~3–4 closed doors). The `open`
  primitive verifiably works (`open W → "The door opens."`).

So a competent *open-door-then-route* sequence reaches the stair with the
primitives as given. GLM 5.2 did not produce that sequence in 45 turns.

## The finding

**Strip the descend/ascend skills and require real navigation, and neither
method descends the curriculum** — both plateau at floor 1–2. The binding
constraint is **navigation to the stairs** (multi-room routing + door management
+ monster handling), and that is now squarely the agent's job:

- random exploration (Go-Explore) rarely produces the exact door-open → corridor
  → next-door → `>` sequence; it stalls at floor 1–2;
- a reasoning LLM (Voyager), given factual blocker reports and the open/kick/move
  primitives, *attempts* the right actions but does not reliably chain a
  multi-door route to the stair within the turn budget.

This directly confirms the hypothesis that the `descend` / `explore_and_descend`
skills were doing essentially all the work — they bundled the (hard) navigation +
the descent. It matches prior harness/NLE findings (methods tie a random walk at
~dlvl 1 without a navigation skill). Crucially, the navigation here was solved by
*neither the developer nor a pre-baked tool* — it is left to the algorithm, and
the algorithm is not yet up to it.

## Algorithms — re-implementable pseudocode & spec

Everything below is enough to re-implement from scratch. Both algorithms run on
the **same environment** (described first), use **only real game primitives**, and
share the **same scoring** (curriculum floor + tour progress).

### Shared environment — `CurriculumEngineEnv`

A thin subclass of the engine env (`nethack_core/curriculum_engine_env.py`).

- **Character / vision:** female-neutral Valkyrie (`"Val-hum-neu-fem"`),
  `reveal_map = 1.0` (full vision; reveals all terrain incl. secret
  corridors/doors). Default seed 19; `reset(seeds=(s, s))` seeds both the level
  generator and display RNG.
- **`curriculum_floor(obs) -> int`:** maps absolute dungeon position to a 1..6
  tour floor. DoD levels 1/2/3 → 1/2/3; Gehennom levels 48/49/50 → 4/5/6;
  anything else → 0. (Uses `blstats` depth + `dnum` = `blstats[23]`.)
- **Internal cross-branch jump (never exposed to the agent):** the only
  non-standard mechanic. The agent always issues the *real* stair commands `>` /
  `<`. The env intercepts **pre-step**: if the hero genuinely stands on the
  Dungeons-of-Doom-3 down stair (`nle_hero_on_stair()` C query returns +1) and
  takes `>`, the env fires `nle_goto_abs(Gehennom, 48)`; taking `<` while on the
  Gehennom-48 up stair fires `nle_goto_abs(DoD, 3)`. There is **no** descend or
  jump command the agent can call — it must find and stand on the real stair.
  (Pre-step interception is required: a `goto_abs` issued *after* a real descent
  step does not process; a single fresh `goto_abs` does.)
- **Snapshot/restore:** `env.snapshot() -> handle`, `env.restore(handle)`,
  `env.free_snapshot(handle)` — full engine-state save/load (used by Go-Explore).
  `env.engine.reseed(core=, disp=)` re-randomizes without changing position.
  **Fidelity verified** (DoD-1 and Gehennom-48): restore + a fixed step sequence
  reproduces snapshot + the same sequence byte-for-byte across **all 27 blstats
  (HP, max-HP, hunger, the condition bitmask, …), the glyph map + monsters, and
  the rendered chars/colors** — including on repeated restores after abandoning a
  different branch. Caveat: `restore()` rewrites engine state but does not refill
  the numpy obs buffers until the next `step()`; Go-Explore always steps after
  restoring, so it reads the correctly-restored state.

### Coordinate & map conventions (both algorithms)

- `obs.chars` / `obs.glyphs` are flat length-`21*79`; reshape to `(21, 79)` =
  `(row=y, col=x)`. Hero position is `(x, y) = (blstats[0], blstats[1])`.
- **Pathfinding (`navigation.pathfinding`) uses `(x, y)` order**: `a_star(grid,
  (sx,sy), (gx,gy))` and `reachable_set(grid, (sx,sy))`, internally indexing
  `grid[y, x]`. `a_star` returns a list of NLE compass-action ids (the start tile
  excluded), or `None`. `reachable_set` is the flood-fill of tiles `a_star` could
  reach (start included).
- **Walkability is decided from glyphs, not chars** — chars can't tell an open
  door/doorway (`'|'`/`'-'`) from a wall. `_walkview(glyphs)`:
  ```
  v = full((21,79), '|')                # default: BLOCKED
  for cmap glyphs:  v[tile] = CMAP_LUT[glyph - CMAP_OFFSET]   # floor/corridor/
                                                              # open-door/doorway/
                                                              # stairs -> walkable
  for object glyphs: v[tile] = '.'      # items on floor are walkable
  # everything else (monsters, CLOSED doors '+', walls, rock) stays '|' = BLOCKED
  ```
  Closed doors and monsters are deliberately **non-walkable** — passing them is
  an explicit agent action (open/kick/attack), not something navigation does.

### Scoring (both algorithms)

```
MAX_FLOOR = 6
progress(floor, bottomed) =
    0                         if floor == 0
    floor                     if not bottomed          # descending: 1..6
    6 + (6 - floor)           if bottomed              # ascending: 6..11
deepest        = max curriculum_floor ever seen
reached_bottom = deepest >= 6 (ever)
climbed_back   = deepest - (min floor seen after first reaching bottom)
```
Reported per run: `deepest_floor`, `climbed_back`, `reached_bottom`, plus a
per-step `timeseries` (the depth-over-time curve).

---

### Algorithm 1 — Go-Explore (search; no LLM)

**Primitives / action set** (`ACTIONS` with sampling `WEIGHTS`):
- 8 compass single-steps `h j k l y u b n` (weight 1.0 each);
- 8 **run-macros** `("run", dir)` — repeat the real single move up to
  `_RUN_MAX = 12` tiles until the hero stops moving (blocked/event); this is just
  "hold the movement key", pure real movement (weight 4.0 each — biased to cover
  corridors fast);
- `search` `'s'` (1.0); real stairs `'>'` (3.0) and `'<'` (3.0).

**State:** an `archive` (dict) of `Cell{ handle=snapshot, progress, max_floor,
traj=[actions], n_visits }`, keyed by
`(progress, dnum, x//3, y//3)` (3×3 spatial bucketing per floor/branch).

```
reset(seed); archive = { key(start): Cell(snapshot, progress(start_floor,F), start_floor, []) }
deepest = start_floor; min_after_bottom = 6; reached_bottom = False

for it in 1..ITERATIONS:
    cell  = select(archive)                 # weighted random, see below
    cell.n_visits += 1
    restore(cell.handle)                    # teleport back to a promising state
    reseed(core=10000+it, disp=20000+it)    # diverge stochastically from it
    running_max = cell.max_floor; traj = copy(cell.traj); done = False

    for _ in 1..EXPLORE_STEPS:              # random rollout
        action = weighted_choice(ACTIONS, WEIGHTS)     # NO forced stair
        obs, done = do_action(action)       # run-macro loops the real move
        traj.append(action)
        floor = curriculum_floor(obs); if floor>0: running_max = max(running_max, floor)
        bottomed = running_max >= 6
        prog = progress(floor, bottomed); nk = key(obs, prog)
        if nk not in archive or prog > archive[nk].progress
                            or (prog == archive[nk].progress and len(traj) < len(archive[nk].traj)):
            archive[nk] = Cell(snapshot(), prog, running_max, copy(traj), n_visits)   # keep best/shortest
        update deepest, reached_bottom, min_after_bottom
        if done: break

    evict_if_over(MAX_CELLS = 6000)         # drop lowest-(progress, then longest traj)
    record timeseries(deepest, climbed_back)

select(archive):   weighted by (1 + progress) / (1 + n_visits)   # prefer deep, under-explored cells
```

**Key choices / why:** cells are the classic Go-Explore "return to a promising
state, then explore"; bucketing by `(progress, dnum, x//3, y//3)` keeps the
archive a coarse map of *where on the tour* you've been; the `progress` score
makes the archive reward the **ascent** after the bottom is reached, not just raw
depth. Snapshot/restore is exact engine state, so "return" is free. Pure random
primitives — the algorithm must *discover* that standing on a `>` and pressing it
descends.

---

### Algorithm 2 — Voyager (LLM composes primitives)

An LLM (GLM 5.2 via Prime Inference) is shown the full-vision map each turn and
emits **one JSON tool call**. The "Voyager" idea: the model composes the
primitives into descend/ascend behavior it was never handed as a skill.

**Tools the LLM may emit** (`_exec` dispatches; each returns
`(obs, done, feedback_string)`):
- `{"tool":"move_to","x":X,"y":Y}` — **generic navigation only** (see below).
- `{"tool":"move","direction":D}` — one real compass step (into monster =
  attack/swap; into door = bump). D ∈ {N,S,E,W,NE,NW,SE,SW}.
- `{"tool":"open","direction":D}` — `'o'` then the direction key.
- `{"tool":"kick","direction":D}` — `^D` (byte 4) then the direction key.
- `{"tool":"search","times":N}` — `'s'` ×N.
- `{"tool":"stairs_down"}` / `{"tool":"stairs_up"}` — real `'>'` / `'<'`.

**`move_to(x, y)` — generic, re-paths every step, never opens/attacks:**
```
for step in 1..80:
    if pos == (x,y): return "reached"
    wv = walkview(glyphs)
    path = a_star(wv, pos, (x,y))
    if path is None:                                  # target not reachable on open terrain
        reach = reachable_set(wv, pos)
        frontier = argmin_{t in reach} manhattan(t, (x,y))   # walk as far toward goal as open ground allows
        if frontier == pos: return blocker_hint(pos, target) # can't even start
        path = a_star(wv, pos, frontier) or return blocker_hint(...)
    obs = step(path[0])
    if died: return "died en route"
    if hero didn't move: return blocker_hint(pos, target)    # a monster stepped onto the route
return "still en route"
```
`blocker_hint` is **factual, non-prescriptive**: lists adjacent closed doors
`'+'` (with directions) and adjacent monsters (`char` + direction) and the rough
direction to the target — then it's the LLM's call to open/kick/fight/search/go
around.

**Main loop:**
```
reset(seed); last_feedback = "Begin."
for turn in 1..MAX_TURNS:
    view = render(env, obs)        # ASCII 21x79 full-vision map + "@ at (x,y)" +
                                   # HP/XP/depth + lists of '>' and '<' tiles +
                                   # an on-stair hint from nle_hero_on_stair()
    content = GLM(system=SYSTEM, user = view + "\nLast action result: " + last_feedback)
    action  = parse_json(content)  # default {"tool":"search","times":1} if null/garbage
    obs, done, last_feedback = exec(action)
    update deepest / climbed metrics; record timeseries(tool, floor, ...)
    if done: break
```

**LLM / API details (load-bearing for re-impl):**
- Endpoint `POST https://api.pinference.ai/api/v1/chat/completions`, model
  `z-ai/glm-5.2`, `response_format={"type":"json_object"}`, `temperature=0.6`,
  **`max_tokens=8000`** (a reasoning model returns `content=None` if the budget
  is too small — parsing must be null-safe).
- Auth: `Authorization: Bearer <api_key>` where the key is the Prime
  `api_key` from `~/.prime/config.json` (the **jonathanliu** team has funds; the
  personal account is $0). **Must send `User-Agent: curl/8.4.0`** — the API edge
  (Cloudflare) 403s the default Python-urllib agent.
- The system prompt enumerates the primitives and tells the model *how to react
  to a blocker report* (closed door → open, "locked" → kick; monster → move into
  it; no route → search or pick another tile) — but the decision is the model's.

---

### How it evolved (and why the numbers are what they are)

1. **v1 — skills (cheating).** A `descend` / `explore_and_descend` skill bundled
   navigation **and** the stair-take. Result: ~100% reached the Elemental Planes.
   But the skill did all the work — not a measure of the agent.
2. **v2 — still developer-assisted.** Skills removed, but `move_to` *itself*
   opened/kicked doors, attacked monsters, and best-effort-pushed through
   blockers; Go-Explore force-took any stair it landed on. Result: floor 1–2.
   Flagged as the *developer* solving navigation — "not in the spirit."
3. **v3 — in-spirit (this report).** `move_to` is generic and only *reports*
   blockers; the LLM owns `open`/`kick`/`move`/`search`; Go-Explore is pure
   weighted primitives with no forced stair. Navigation intelligence comes only
   from the algorithm/LLM. Result: floor 1–2 — and the diagnostic above proves
   the primitives are *sufficient*, so the wall is the agent, not the tooling.

## What would move the curve (the agent/algorithm axis)

A meaningful "how deep over time" curve needs the *agent* to get better at
navigation — not the developer to hand it a navigation skill. Legitimate avenues,
all of which keep the work on the algorithm's side:

- **Voyager skill learning that actually persists** — let the LLM author and
  re-use its own navigation routines (a real skill library), so the
  open-door-then-route sequence it occasionally finds is captured and replayed,
  rather than re-derived from scratch each level.
- **Go-Explore with a richer cell representation / longer budget** — reward
  reaching new rooms (door transitions), not just new tiles, so the search is
  pushed toward the door-opening that unlocks the stair.
- **A stronger policy model** — the primitives are sufficient; a model that plans
  multi-step door routes would descend with no tooling change.

The deep curriculum content (the 3→48 jump, the climb back) is fully wired and
reachable *the moment an agent can navigate to a downstair* — so the depth-over-
time comparison becomes informative as soon as the agent side improves.

Runners: `approaches/go_explore/curriculum_go_explore.py`,
`approaches/voyager/curriculum_voyager.py`,
`approaches/go_explore/curriculum_go_explore_llm.py`. Raw outputs:
`outputs/curriculum_experiments/`.
