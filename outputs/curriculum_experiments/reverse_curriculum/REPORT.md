# Reverse-curriculum reachability on the compressed NetHack tour

*Author: Jonathan Liu · run 2026-06-27 · agent: GLM-5.2 via Prime Inference + a no-LLM scripted baseline*

## TL;DR

We set out to find **what kind of curriculum lets a legal-primitives-only agent
learn to climb back up the compressed NetHack tour, without ever being handed an
illegal ascend/descend skill.** Two experiments — a GLM-5.2 agent sweep (partial:
Prime ran out of credits mid-run) and a complete, free, no-LLM scripted baseline
(20 seeds) — converge on one answer:

> **The binding constraint is not curriculum length — it is navigation.** Climb
> success is concentrated almost entirely in the *single-floor* climb (nearest the
> goal) and collapses immediately for any longer climb, because on most levels the
> agent simply cannot path to the up-stair with the stock harness. A reverse
> curriculum (start near the goal, extend backward) is therefore **necessary but
> not sufficient**: starting near the goal is the only regime with non-trivial
> success, but the *harness's navigation* has to improve before the curriculum can
> push the start deeper. The curriculum and the harness must co-evolve.

Concretely (P = probability of reaching floor 1, the top):

P(reach the top / floor 1) from each start floor:

| start floor (climb distance) | scripted greedy-nav, 20 seeds | GLM-5.2, real cells |
|---|---|---|
| 2 (1 floor) | **0.30** | **0.67** (4 seeds) |
| 3 (2 floors) | 0.00 | 0.00 |
| 4 (3 floors, crosses jump-up) | 0.00 | 0.00 |
| 5 (4 floors) | 0.00 | *blocked — Prime 402* |
| 6 (5 floors) | 0.00 | *blocked — Prime 402* |

Even the **per-segment** probability (reach just the *next* floor up — the metric
the 90% advancement gate uses) never approaches 0.90: scripted 0.16–0.26, GLM 0.67
at floor 2 then 0.00 at floors 3–4. See `per_segment.png`.

See `ceiling_vs_glm.png` (headline), `nav_ceiling.png`, `scripted_heatmap.png`,
`per_segment.png`, `glm_timeline.png`, `glm_trajectories.png`, and the win replays
`win_seed19_f2.gif` (full 1-floor win to the top) and `win_seed24_f4.gif`
(climbs Gehennom 48→DoD 3 across the cross-branch jump-up, then gets stuck).

## 1. The question

Teach an agent to traverse a compressed NetHack dungeon **using only legal
primitives** — move, search, open/kick doors, real `>` / `<` stairs — and
**without ever handing it an illegal "ascend"/"descend" teleport**. The engine's
internal `goto_abs` cheat is used *only* to build the level the agent must then
escape on its own; the agent never sees it.

Design hypothesis (the user's framing): the **reverse curriculum** (Florensa et
al. 2017) — start the agent near the goal where the task is short, then push the
start progressively farther — should let it learn to "go backwards" (climb). The
compressed-tour env is an ideal testbed because `goto_abs` + byte-exact snapshots
let us instantiate the agent at *any* point on the tour.

## 2. How the compressed tour works

`CurriculumEngineEnv` compresses NetHack's 50-level descent into a 6-floor
down / 6-floor up tour driven by the agent's **real** stair commands:

| curriculum floor | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| dungeon level | DoD 1 | DoD 2 | DoD 3 | Gehennom 48 | Gehennom 49 | Gehennom 50 |

- **Full vision** (a fork patch reveals the whole level incl. secret
  corridors/doors), so the task is pathfinding-and-acting, not exploration-under-fog.
- Taking the **real** `>` on DoD 3 transparently redirects across branches to
  Gehennom 48 (`nle_goto_abs`) + a one-time stats level-up; the **real** `<` at the
  top of the deep segment jumps back to DoD 3. The agent only ever presses `>`/`<`
  on a staircase it navigated to itself.
- To build a climb start at floor *s* we `goto_abs` the hero there and apply the
  deep stats-upgrade (so it matches a hero that legitimately descended). **That
  teleport is the cheat we hide; the climb is the task we measure.**

## 3. Engine provenance (why a worktree + rebuild)

The env binds fork-only engine symbols (`nle_goto_abs`, `nle_hero_on_stair`,
`nle_num_dungeons`, `nle_dungeon_info`) that exist on fork branch
`feature/curriculum-on-stair` (`23afc7f`). `main` *records the submodule at exactly
that commit*, but the working tree's submodule had drifted to an older commit
without those symbols, so the env failed to load. Fix: a dedicated
`reverse-curriculum` git worktree, submodule synced to the commit `main` pins,
engine rebuilt from source (`nethack_core/build_engine.sh`, ~1 min). The game
engine is never patched.

## 4. Experiment design

Every condition is a **pure climb** measured under **approach B** (episode runs
from the constructed start all the way to floor 1, or until death / a turn budget):

| condition | start | tests |
|---|---|---|
| `climb_from_2..6` | floor 2..6 | climb 1..5 floors to the top |
| `full_tour` | floor 1 | no-curriculum baseline (descend then climb) |

Two complementary sweeps:

1. **GLM-5.2 agent** (Prime Inference, stock `curriculum_voyager` tool loop, one
   JSON tool-call/turn, T=0.6) over seeds {19,0,4,5} × 3 reps.
2. **Scripted greedy-nav baseline** (NO LLM): repeatedly path to the nearest
   up-stair and take it, attack an adjacent blocker, search when no stair is
   visible. Over **20 seeds** with a full 6-floor deep segment × floors 2–6. This
   is free, so it covers every cell the API budget could not, and it isolates the
   *navigation* variable from agent reasoning — the **navigation ceiling**.

Seeds were filtered to those whose Gehennom reaches absolute depth 50 (a
well-defined floors 4–6); many seeds have a shorter Gehennom. Each episode runs in
its own subprocess (the NetHack C engine is process-global).

## 5. The real lesson: navigation is the wall

The first validation episodes exposed that with the **stock** harness the agent
could not climb even one floor — not because the curriculum was too long, but
because **legal-primitive navigation is the binding constraint**. Three concrete,
reproducible bugs (all fixed in `reverse_curriculum_sweep.py`, all staying within
legal primitives — no new teleport-like power):

1. **Descent-biased map hint.** `curriculum_voyager._render` always points the
   agent at the *down* stair when one is visible (always). A *climbing* agent was
   told to go down every turn. Fix: a climb-aware hint pointing at `<`.
2. **`move_to` can't handle doors or NetHack movement rules.** The stock navigator
   (a) stops dead at closed doors, (b) plans **diagonal** moves NetHack forbids
   *into/out of a doorway* (wedging at door tiles), and (c) treats the blank `' '`
   glyph — which the char-LUT uses for *both* dark floor and solid stone — as
   walkable, routing into walls. Fix: a door-aware BFS (`nav_to`) that routes
   through closed doors and **opens/kicks them orthogonally**, uses 8-connectivity
   but **forbids diagonal steps in/out of door tiles** (cmap 12–16), and treats
   `' '` as blocked.

Effect: the same `climb_from_2` episode went from **0 floors in 45 turns → top in
2 turns**. The first lesson is therefore about the **harness**, and any curriculum
result is only meaningful on top of a navigator that can reach stairs.

## 6. Results

### 6a. Navigation ceiling (scripted, complete — `nav_ceiling.png`, `scripted_heatmap.png`)

Across 20 full-depth seeds, the greedy-nav climber:

| start floor | n | P(reach top) | P(reach next floor) | mean floors climbed | median stuck floor |
|---|---|---|---|---|---|
| 2 | 20 | 0.30 | 0.30 | 0.30 | 2 (the start) |
| 3 | 20 | 0.00 | 0.25 | 0.25 | 3 |
| 4 | 20 | 0.00 | 0.15 | 0.15 | 4 |
| 5 | 20 | 0.00 | 0.05 | 0.05 | 5 |
| 6 | 20 | 0.00 | 0.15 | 0.15 | 6 |

The dominant outcome at **every** start floor is *stuck on the start floor* — the
climber cannot reach that level's up-stair. It reaches the top **only** from floor
2 (~30%), and **never** from floors 3–6 (it occasionally climbs one floor but never
chains to the top). Reachability is **seed/level-specific** (some seeds navigate a
floor, others do not), not a smooth function of depth.

**Reproducibility fix (initial-prompt freeze).** A re-test 3 days later showed
*every* construct landing on floor 1 — `goto_abs` returning success but no level
change. Root cause: the game starts blocked on the **`--More--` welcome prompt**;
until it is dismissed (space+enter) *every* command — move, stairs, `goto_abs` — is
a silent no-op, so the hero never leaves floor 1. This also explains the earlier
"seed-22 only" fake wins: the prompt freeze is **intermittent across process
launches**, and on the first run it happened to hit only seed 22's process. The fix
dismisses the prompt in `construct_start`; with it, all 20 seeds construct
deterministically (seed 22 included, now a genuine floor-2 result). A
construct-validation guard (reject any landing floor ≠ intended) remains as
defense-in-depth. The conclusion is unchanged and now reproducible run-to-run.

**Why the climber gets stuck (diagnosis over 100 cells):** **89% of failures are
monster-related** — 51% a monster blocking the path (not adjacent, so the climber
can't engage) and 38% perpetual combat with an adjacent monster/pet (the starting
pet, which it "attacks" = swaps with, oscillating). Doors (1%) and hidden passages
(3%) are negligible.

**Fight-through ablation (does solving monsters lift the ceiling? — barely).**
Adding a navigator that paths *through* monster tiles and melees the blocker
(`nav_to(fight=True)`) provably reaches up-stairs the stock navigator cannot
(verified per-level), and lets the climber chain an extra floor on some seeds — but
the **aggregate P(reach top) and mean-climbed are essentially unchanged** (floors
3–6 still 0.00). Two reasons: reaching the *top* needs every floor's blocker solved,
and the deep Gehennom levels are long, monster-dense **mazes** (e.g. a 141-tile path
through 7+ wandering monsters) where greedy per-step re-pathing stalls regardless of
melee. So monsters are the *proximate* blocker but not the whole story; a materially
better navigator needs maze-robust global pathing + combat + the pet handled, not
melee alone.

### 6a-bis. Seeing a real win (`win_seed19_f2.gif`, `win_seed24_f4.gif`)

Two deterministic replays make the result concrete:
- **`win_seed19_f2`** — a clean full win: the `@` paths across DoD 2 to the `<` and
  climbs to DoD 1 (the top).
- **`win_seed24_f4`** — the agent climbs from **Gehennom 48 to DoD 3, crossing the
  internal cross-branch jump-up**, then gets **stuck on DoD 3** unable to reach its
  up-stair. One episode showing both a genuine win and the exact failure mode that
  caps every deep climb.

### 6b. GLM-5.2 agent (partial — `glm_trajectories.png`)

| condition | n (real) | P(reach top) | mean wall (s) |
|---|---|---|---|
| `climb_from_2` | 12 | **0.667** | 445 |
| `climb_from_3` | 12 | 0.0 | 1223 |
| `climb_from_4` | 11 | 0.0 | 1252 |
| `climb_from_5/6`, `full_tour` | 0 valid | — | *Prime 402* |

The GLM agent beats the scripted baseline on the 1-floor climb (0.67 vs 0.30) —
it is more persistent on the navigable seeds — but, exactly like the scripted
baseline, it **never climbs 2+ floors** in budget, and on `climb_from_3/4` it
typically fails to climb even the first floor (it gets stuck reaching DoD 3's
up-stair, which the scripted sweep confirms is often unreachable). The two
independent methods agree on the shape: **a sharp cliff right after the 1-floor
climb.**

### 6c. The Prime 402 incident (operational finding)

Mid-sweep, Prime Inference began returning **HTTP 402 Payment Required** (account
out of credits). Because the original loop silently swallowed LLM errors into a
no-op turn, the later episodes (`climb_5/6`, `full_tour`) *ran their full turn
budget in 8–14 s doing nothing* and masqueraded as real zero-success data. The
timeline (`glm_timeline.png`) shows this vividly: long real episodes, then an abrupt
wall of zero-duration bars the instant credits ran out. Fixes applied:
- `llm_call` now retries 429/5xx with exponential backoff and **raises** on 402
  (out of credits) instead of nulling the turn; episodes abort with an `llm_error`.
- The analyzer **drops** invalid (no-LLM / errored) episodes (37 of 72 here).
- Lesson for the continual-harness loop: **cap concurrency and monitor spend**.
  8 workers both degraded Prime latency (≈20 s/turn) and burned the balance fast.

## 7. Timeline (`glm_timeline.png`)

A Gantt of the GLM run, each bar one episode (bold outline = reached floor 1),
reconstructed from episode-completion mtimes minus measured wall-time. It doubles
as the clearest picture of the 402 cutoff: the deep/full-tour conditions all
collapse to instant bars once the account is exhausted.

## 8. What this says about "what curriculum works"

1. **A reverse curriculum is the right instinct but won't carry the load alone.**
   The only regime with meaningful success is the start *adjacent to the goal*
   (1-floor climb) — exactly where reverse curriculum begins. But the success
   ceiling there is already low (~0.3 scripted), and it falls off a cliff at 2
   floors. Extending the start backward (the whole point of the schedule) is
   pointless until the agent can clear single floors reliably.
2. **The first thing the harness optimizer must fix is navigation reachability of
   the up-stair**, not the curriculum schedule: robust stair-pathing through
   monsters (combat), hidden-passage search, and Gehennom hazards (lava). The
   curriculum is most useful here as a *diagnostic* — it localizes exactly where
   navigation breaks (immediately past one floor, and hard at the floor-4→3
   cross-branch jump).
3. **Difficulty is per-level, not smoothly per-depth.** Reachability is bimodal
   across seeds (navigable or stuck-at-start), so an adaptive scheduler should gate
   on *measured per-(seed,floor) success*, not on depth alone — which is exactly
   what the designed 90%-gate + geometric-replay scheduler does.

## 9. Next steps

- **Finish the GLM curve**: top up Prime credits, then
  `--launch --seeds 19 0 4 5 --reps 3 --workers 3` (resume skips done cells; lower
  concurrency + the new backoff avoid the degradation/credit burn).
- **Improve the navigator** (the actual bottleneck): combat-through-blockers in
  `nav_to`, hidden-passage search escalation, lava/again-handling. Re-run the free
  scripted ceiling after each change to measure the lift — a tight, zero-cost
  harness-optimization loop.
- **Then** wire the adaptive reverse-curriculum scheduler the user specified:
  frontier of unlocked start floors, advance on ≥90% next-floor success, geometric
  replay weighted to the most-recently-unlocked floor to prevent forgetting,
  episodes start→goal (approach B).

## Reproduce

```
# in the reverse-curriculum worktree, engine built via nethack_core/build_engine.sh
PI_API_KEY=$(python -c "import json,os;print(json.load(open(os.path.expanduser('~/.prime/config.json')))['api_key'])")

# free, complete navigation-ceiling sweep (no API):
python approaches/voyager/scripted_nav_reachability.py --seeds-range 40 \
    --out outputs/curriculum_experiments/scripted_nav

# LLM agent sweep (needs Prime credits; or --model gemini-2.5-flash for the
# Gemini OpenAI endpoint, subject to free-tier daily caps):
PI_API_KEY=$PI_API_KEY python approaches/voyager/reverse_curriculum_sweep.py --launch \
    --seeds 19 0 4 5 --reps 3 --workers 3 \
    --out outputs/curriculum_experiments/glm5.2_partial

# figures:
python approaches/voyager/analyze_reverse_curriculum.py --out <run-dir>
python approaches/voyager/plot_final.py
```
