# NetPlay's harness vs ours — architecture + full pseudocode

A side-by-side of how **NetPlay** (Jeurissen et al., *Playing NetHack with LLMs*,
CoG 2024 — `github.com/CommanderCero/NetPlay`) drives an LLM agent through NetHack
versus how **our** harness (`environments/nethack`) does, with pseudocode for the
load-bearing loops. The goal is to pinpoint why ours plateaus at **~40% per-level
descent reliability (mean max dlvl ~1.4)** while NetPlay reaches **2.6** — and
which of those differences is the real cause.

Both are the *same shape*: an LLM picks ONE high-level skill per turn, the skill
runs to a natural stopping point, then the LLM picks again. The difference is
**what's underneath the skills**.

---

## 0. TL;DR of the difference

| | NetPlay | Ours |
|---|---|---|
| LLM role | pick 1 skill/turn (it only worked with **GPT-4**) | pick 1 tool/turn (Qwen3-VL / Sonnet — both ~1.3) |
| Map representation | **persistent `Level` model** from glyphs: `features`, `has_seen`, `search_count`, `door_open_attempts`, **room/corridor graph** | **stateless** per-step glyph→clean-chars grid + an a_star; `search_count` is the only persisted state |
| Exploration | `explore_level`: BFS **distance map** + **visit-mask** (unseen-rock-adjacent) + **search-mask** (prioritized) → provably sweeps the whole level incl. hidden passages | `find_frontiers` + nearest-frontier + a **capped** dead-end/perimeter search → **incomplete on ~60% of levels** |
| Low-level engine | **bundled `autoascend`** (a complete, tuned NetHack bot): pathfinding, level tracking, monster/item logic | hand-written a_star + glyph classification |
| Combat / survival | `melee_attack` (pursue+kill), `avoid_monsters` flag, real eating/altar/prayer logic | none in-skill; danger-**halt** back to the LLM and hope it heals |
| Skill mechanics | Python **generators** yielding `Step`s; cleanly interruptible on popups | one skill = a list of actions OR a `pre_executed` self-stepping loop; coarser |

**Conclusion the evals support:** the bottleneck is the **exploration/level-model
layer (rows 2–4)**, not the LLM. NetPlay's `autoascend`-backed `explore_level`
*guarantees* it finds the downstairs; ours finds it ~40% of the time.

---

## 1. The shared top-level loop

Both: `while not done: skill = LLM_pick(obs); run(skill); obs = render()`.

### NetPlay — `netplay/nethack_agent/agent.py :: NetHackAgent.step`

```
def agent_loop(task = "Win the game"):
    while True:
        # 1. LLM chooses ONE skill (name + kwargs + free-text "thoughts")
        choice = skill_selector.choose_skill(self)        # -> SkillSelection
        if choice.skill is FINISH_TASK: return

        # 2. run the skill as a generator, wrapped so --More-- never eats moves
        strat = execute_skill(choice.skill, choice.kwargs)   # generator of Steps
        strat = skip_more_messages(strat)                    # press SPACE on --More--
        strat = update_objects(strat)                        # refresh tracked entities
        yield from strat                                     # actually step the game

        # 3. anti-stuck: if no GAME TURN elapsed for N tries, give up the task
        if blstats.time == last_time:
            tries += 1
            if tries >= MAX_TRIES_PER_GAMESTEP: yield Step.failed("no progress"); return
        else:
            last_time = blstats.time; tries = 0

def skip_more_messages(gen):           # the move-eating fix
    for step in gen:
        yield step
        if step.is_done(): return
        while self.showing_more_message:           # a --More-- is up
            yield self.step(KEYPRESS_SPACE)         # clear it before the next real action

# Skill selection = an LLM call over a rich textual state description
def choose_skill(agent):
    prompt = build_prompt(agent.describe_current_state(),  # rooms, items, monsters, msgs
                          skill_repository,                 # name+desc+params of each skill
                          task)
    reply  = LLM(prompt)                                    # GPT-4
    return parse_json(reply)        # { skill, kwargs, thoughts }  (retried on bad JSON)
```

### Ours — `environments/nethack/nethack.py :: env_response`

```
# verifiers drives the chat loop; env_response is called once per LLM message.
def env_response(messages, state):
    tool_calls = messages[-1].tool_calls
    if not tool_calls:
        return user_msg("You must call a tool.")            # force native function-calling

    name, args = tool_calls[0].name, json(tool_calls[0].arguments)
    result = skill_registry.call(name, env, state.obs, **args)   # -> SkillResult

    if result.pre_executed:                 # closed-loop skill already stepped the env
        total_reward, last_obs = result.pre_reward, result.final_obs
        terminated, truncated  = result.pre_terminated, result.pre_truncated
    else:                                    # normal skill returns an action list
        total_reward = 0
        for i, act in enumerate(to_action_indices(result.actions)):
            last_obs, r, terminated, truncated, _ = env.step(act)
            total_reward += r
            if len(actions) >= 4 and check_halt(last_obs, hp_before):   # HP-drop /
                break                                                   # hostile / prompt
    auto_dismiss_menus(env, state)           # press ESC/CR/y/n until the prompt clears
    state.obs = shape(last_obs)
    return user_msg(render_observation(state.obs))          # ASCII/JSON/TOON/IMG

# The LLM sees: the system prompt (strategy + skill cheat-sheet) + the rendered obs +
# the tool schemas for the selected skill_set (netplay = move_to, explore_and_descend,
# attack, descend, search, kick, eat, pray, ... 17 tools).
```

**Same shape.** Both force a single high-level tool/skill per turn and re-render.
Ours adds a `pre_executed` path so a skill can run its own internal loop (that's how
`explore_and_descend` works); NetPlay always runs skills as generators.

---

## 2. The map / level model — **the first big divergence**

### NetPlay — `netplay/nethack_agent/tracking.py :: Level` (glyph-derived, persistent)

```
class Level:
    glyphs:            int[21,79]    # raw NLE glyphs, last seen
    features:          int[21,79]    # terrain glyph per tile (floor/wall/door/stairs/...)
    has_seen:          bool[21,79]   # have we ever observed this tile?
    search_count:      int[21,79]    # times we've searched adjacent to here
    door_open_attempts:int[21,79]    # times we've tried to open each door
    graph:             RoomGraph     # rooms + corridors as nodes, with exits

    def update(px, py, glyphs, chars):
        self.glyphs = glyphs
        feat = G.is_dungeon_feature(glyphs)         # glyph-group test, NOT tty chars
        self.features[feat] = glyphs[feat]          # remember terrain even under items/monsters
        self.has_seen[<currently visible>] = True
        recompute_room_graph()                      # flood-fill rooms/corridors via features

    def walkable_mask():                            # open doors are a DISTINCT glyph
        return isin(features, FLOORS|CORRIDORS|DOORWAYS|OPEN_DOORS|STAIRS)
    def get_distance_map():  return BFS(player, walkable_mask())     # dist to every tile
    def get_path_to(x,y):    return BFS_path(player, (x,y), walkable_mask())
```

Key properties: it is **persistent** (accumulates `has_seen`, `search_count`,
`door_open_attempts` across turns), it derives terrain from **glyph groups** (so an
open door is never confused with a wall), and it maintains a **room/corridor graph**.

### Ours — `nethack_harness/tools/skills.py` (glyph-derived, but **stateless per call**)

```
def glyph_clean_chars(glyphs):           # rebuilt every step; no has_seen / room graph
    out = ' '[21,79]                     # default: unexplored
    for each tile:
        if is_cmap(g):  out = LUT[cmap(g)]   # '>' down, '<' up, '+' closed door,
                                             # '.' walkable (incl OPEN doors+doorways),
                                             # '|' wall, ' ' dark/unknown
        elif is_monster|pet|object(g): out = '.'   # walkable terrain under it
    out[player] = '.'
    return out                            # an UNAMBIGUOUS char grid (the one real win we share)

# we then run the SAME a_star/find_frontiers the rest of the harness uses, over this grid.
# the ONLY thing we persist across calls is nle_env._explore_search_count (per-tile).
```

We fixed the **open-door-vs-wall ambiguity** at the source (the same idea NetPlay
uses) — that was the single biggest bug. **But** we don't keep a persistent
`has_seen`/room graph, and we recompute everything each step. That's tolerable for
movement but it means our *exploration policy* has no global memory of "which
regions are fully explored vs still have unseen rock" — which is exactly what makes
NetPlay's coverage complete.

---

## 3. Exploration — **the decisive divergence (why we cap at ~40%)**

### NetPlay — `explore_level` (provably sweeps the whole level + hidden passages)

```
@fail_on_popup
def explore_level(agent, search_prio_limit=None, door_open_count=4):
    while True:
        yield from open_neighbor_doors(agent)          # walk INTO adjacent closed doors
                                                        #   (autoopen), retry up to 4
        dist   = agent.get_distance_map()              # BFS distances to all reachable tiles
        visit  = compute_visit_mask(agent)             # tiles ADJACENT to unseen ROCK,
                                                        #   plus not-yet-opened doors
        search = compute_search_mask(agent)            # tiles worth SEARCHING, scored by:
                                                        #   + door surrounded by stone (+250)
                                                        #   + dead-ends / few-walkable-neighbors
                                                        #   - search_count^2  (don't re-search)
        explore = (visit | search) & (dist != -1)      # reachable frontier-or-search tiles

        if not explore.any():
            yield Step.completed("level fully explored")    # <-- guaranteed terminal
            return

        target = nearest tile in `explore` by `dist`       # distance-map nearest, no oscillation
        for step in move_to(agent, *target): yield step     # ONE step at a time, re-checks
        if target is a SEARCH tile:
            for _ in range(5): yield agent.step(SEARCH)      # search here, increments search_count
```

What makes this *complete*:
1. `compute_visit_mask` is **unseen-rock-adjacent** — it never runs out until every
   tile bordering unknown space has been visited *or* searched.
2. `compute_search_mask` **prioritizes** the exact places hidden passages hide
   (dead-ends, doors-walled-by-stone) and **deprioritizes already-searched tiles**
   via `search_count` — so it searches efficiently and *terminates*.
3. The **distance map** gives a globally-nearest target → no oscillation, no
   re-visiting; it monotonically shrinks the frontier.
4. Doors are opened by **walking into them** (autoopen), tracked by
   `door_open_attempts` so it doesn't loop.

`explore_level` returns `completed` only when there is genuinely nothing left to
reveal — which means by the time the LLM calls `descend`, the `>` *has* been found
(or the level is provably sealed, which standard levels never are).

### Ours — `explore_and_descend` (one-shot per floor, capped search)

```
@registry.register("explore_and_descend")          # pre_executed: steps the env itself
def explore_and_descend(env, obs, max_floors=1, max_game_steps=400):
    while steps < budget and floors < max_floors and alive:
        chars, me = obs_map()                       # glyph_clean_chars + player (rebuilt)
        # --- survival: hand control back to the LLM on danger ---
        if hp <= hpmax//2:        return halt("HP low — heal/flee")     # LLM decides
        if hunger >= WEAK:        return halt("hungry — eat")
        visited.add(me)                              # mark tiles we stand on (anti-oscillate)

        # --- descend if we know where the down-stair is ---
        if '>' visible: down_stair = its position
        if down_stair:
            if me == down_stair:  do(MORE); do(DOWN); floors += 1; continue   # descend
            step ONE move along a_star(me, down_stair); continue

        # --- else: explore nearest unvisited OPEN frontier ---
        fronts = [f for f in find_frontiers(chars)
                  if walkable(f) and f not in visited]          # walkable adj to ' '
        best = nearest fronts by a_star
        if best:
            step ONE move toward best
            if didn't move: visited.add(best)        # bumped -> blacklist
            continue

        # --- else: open the nearest reachable CLOSED door ---
        d = nearest closed door (from glyphs) with a walkable orthogonal stand-tile
        if d:
            step toward the stand-tile; when adjacent: move INTO door (autoopen) or KICK
            continue

        # --- else: SEARCH dead-ends / room perimeter for hidden passages (CAPPED) ---
        if search_actions >= search_budget: break    # <-- bail so we don't starve
        t = best walkable tile adjacent to a wall that borders unseen ' '
        if t is None: break                          # <-- give up the level
        step toward t; search x5; search_count[t] += 5; search_actions += 5

    return SkillResult(pre_executed=True, reward, final_obs, feedback=...)
```

### Why ours descends only ~40% of levels — the concrete gaps vs `explore_level`

1. **No distance-map "nearest frontier"** — we call `a_star` per frontier and pick
   the shortest. Functionally similar but more fragile; NetPlay's single BFS
   distance map is what cleanly prevents oscillation and guarantees the nearest.
2. **Search is *capped* (`search_budget`), and bails (`break`) when it can't find a
   dead-end.** NetPlay's search-mask is **unbounded-until-exhausted** and
   prioritized, so it *will* find a hidden passage; ours stops early to avoid
   starvation and therefore **misses hidden downstairs**. This is the #1 cause of
   the 60% failures.
3. **No `has_seen` / room-graph memory.** Our `visited` is just tiles-stood-on;
   NetPlay knows, per tile, whether unseen *rock* still borders it, so its frontier
   never falsely empties. Ours can declare "no frontier" while unexplored regions
   remain behind a wall that needed one more search.
4. **No combat.** We path *through* monster tiles (treated walkable) → we attack by
   bumping, take damage, and **die**; NetPlay has `melee_attack` (pursue + kill
   cleanly) and an `avoid_monsters` flag. Our only defense is the HP **halt** back
   to the LLM — and a weaker LLM doesn't reliably heal.
5. **Coarser LLM interaction.** `explore_and_descend` runs a whole floor
   autonomously (`pre_executed`) and only breaks per-floor / on danger. NetPlay's
   skills are generators that the framework can interrupt on any popup, giving the
   LLM finer control — though this matters less than #2–#4.

---

## 4. Doors, prompts, survival — smaller divergences (mostly closed)

| Concern | NetPlay | Ours | Status |
|---|---|---|---|
| Open door looks like a wall in tty | uses glyph `features` | `glyph_clean_chars` (glyph LUT) | **closed** ✓ |
| Closed doors block pathing | `walkable_mask` excludes them; `open_neighbor_doors` walks in | LUT marks `+` blocked; door-step walks in / kicks | **closed** ✓ |
| `--More--` eats moves | `skip_more_messages` (SPACE loop) | `do()` dismisses `--More--` each step | **closed** ✓ |
| Standing on `>` hides it (`@`) | tracked in `features`/graph | remember `down_stair` position | **closed** ✓ |
| Don't search to death | prioritized + `search_count`, plus food/altar logic | `search_budget` cap + HP/hunger halt | **partial** — cap causes misses |
| Monsters | `melee_attack`, `avoid_monsters` | none (LLM only) | **open** ✗ |
| Backed by a full bot | **`autoascend`** | no | **open** ✗ |

---

## 5. What this says about closing 1.4 → 2.6

The evals (Qwen3-VL **1.38**, Sonnet-4.5 **1.25**, NetPlay/GPT-4 **2.6**) plus this
diff point at the same conclusion: **the model is not the lever; the exploration +
survival layer is.** To approach 2.6 without porting all of `autoascend`, the two
highest-value changes are:

1. **Make exploration provably complete** — replace the capped search with an
   `explore_level`-style **visit-mask + prioritized search-mask over a persistent
   `has_seen`/`search_count` map**, so a hidden downstair is always found (bounded
   by a turn budget the LLM can extend across calls, not a hard give-up).
2. **Add minimal survival** — a `melee_attack`-style "kill the adjacent blocker"
   and "flee + rest when low" so the agent survives to the next floor (today it
   dies on floor 2). This unblocks *multi-floor* dives, which is what turns
   "reach dlvl 2 sometimes" into "average 2.6".

Both are squarely the `autoascend`-grade work NetPlay's authors leaned on — which
is also why they reported *no* non-GPT-4 model worked: without robust skills, even
a strong model has nothing reliable to call.
