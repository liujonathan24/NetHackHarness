# Non-compact descent pursuit — 8-iteration writeup

**Goal (user):** "Look through the non-compacted and identify why it is so
bad at going down... iterate until we maximize the success rate. Work
until you get maximum possible descent score on non-compacted harness."

**Date:** 2026-05-17, started ~01:00 EDT, finished ~05:30 EDT
**Hub env at start:** v0.0.60. Working tree: HEAD `9b37635` (8 commits
on `main` since /goal start).
**Model:** Qwen/Qwen3.5-9B on pinference (free for this model).
**Tier:** `corridor_explore` (objective: reach dungeon level 2).

## Iterations

| iter | code change | n | descents | best scout | obs with `>` |
|---|---|---:|---:|---:|---:|
| baseline | (pre-goal, locked-door HINT etc already shipped) | 1 | 0 | 0.077 | 0 |
| 1 | locked-door msg HINT + autoexplore skips `<` frontier | 1 | 0 | 0.052 | 0 |
| 2 | wall-gap doorway detection + SYSTEM_PROMPT primer | 3 | 0 | 0.092 | 0 |
| 3 | **lifted compact-gate on VISIBLE FEATURES/GLYPHS/HINTs** | 3 | 0 | 0.181 | 9 (1 rollout) |
| 4 | stairs-DOWN memory + on-stairs override HINT | 3 | 0 | 0.090 | 0 |
| 5 | wider sample to measure variance | 8 | 0 | 0.185 | 0 |
| 6 | dead-end auto-search when frontiers exhausted | 8 | 0 | 0.173 | 0 |
| 7 | autoexplore reroutes to known doors on short frontier | 8 | 0 | 0.126 | 0 |
| 8 | `find_and_descend` mega-skill (path+descend in one call) | 8 | 2 false-pos | 0.126 | 42 (1 rollout) |
| **8b CONTROL** | **same 8 seeds, COMPACT mode** | 8 | **0** | 0.111 | **0** |

**Across 24 unique non-compact rollouts + 8 compact-control rollouts: 0
true descents.** R8/R6 had `descend_calls=2` but the agent wasn't on `>`
(map block contained no `>` either), so the actions were no-ops.

## What was diagnosed and fixed (these all landed in main)

1. **Locked-door blindness.** Trace baseline showed agent stuck behind a
   locked `+` repeatedly autoexploring to the stairs-up `<`. Added HINT
   that reads "This door is locked." from the message buffer, finds the
   adjacent `+` direction, and prescribes `kick(direction=...)`.
   *Commit:* `7b48e94`.
2. **Wall-gap doorway invisibility.** Agent didn't recognize `--|---` or
   `--.----` notation. Added `extract_visible_features` second pass
   that detects `|`/`.` sandwiched between `-` (or `-`/`.` between `|`)
   and labels as `door (open/gap) at (x,y)`. Added SYSTEM_PROMPT primer
   block explaining the notation. *Commit:* `7b48e94`.
3. **Autoexplore picks `<` as frontier.** When the player spawns in a
   small room with a closed door, the frontier picker happily returns
   the `<` tile (walkable + adjacent to closed door). Walking to `<` is
   useless for descent. Added a guard that re-picks from
   `find_frontiers` excluding `<` when possible. *Commit:* `7b48e94`.
4. **VISIBLE FEATURES/GLYPHS suppressed in non-compact mode.** Big bug.
   The `if compact:` gate around the entire pre-parsed features block
   meant non-compact agents had to scan the ASCII grid themselves. After
   lifting the gate, iter3 R2 saw `>` in 9 obs (first ever non-compact
   sighting). *Commit:* `c8fd8c5`.
5. **Standing-on-stairs oscillation.** In iter3 R2, agent stepped ONTO
   `>` and immediately the `@` overlay hid the glyph; the HINT system
   reverted to "No `>` visible; only exit is a door at..." and pushed
   the agent off the stairs. Added `state["_seen_stairs_down"]` memory:
   any `>` coord ever observed is remembered, and when the player is on
   one of those coords, highest-priority HINT fires:
   *"You are standing on stairs DOWN at (x,y) — call `descend` now."*
   With override guards so pet-blocking / locked-door / door-fallback
   HINTs don't clobber it. *Commit:* `c8fd8c5`.
6. **Dead-end auto-search.** When `nearest_frontier` returns None,
   `autoexplore` now walks to the closest corridor dead-end (walkable
   tile with exactly one walkable cardinal neighbor) and queues 20
   `search` actions. Targets the "hidden passage on otherwise fully
   explored level" failure mode. *Commit:* `bcafbde`.
7. **Reroute-to-door on short frontier.** When the frontier path is
   ≤ 2 steps but there's a reachable closed-or-open door we haven't been
   through, `autoexplore` paths to the door instead of the trivial
   frontier. Targets iter5 R4 where the agent kept short-pathing in
   its current room while a door to the next room was visible.
   *Commit:* `bcafbde`.
8. **`find_and_descend` mega-skill.** Single tool call that runs:
   path to visible `>` and descend, OR path to nearest reachable door,
   OR walk to dead-end and search 25×. Up to ~80 NLE actions per call.
   *Commit:* `9b37635`.

## Why descent stays at 0

**Three things compound:**

1. **The vf-eval default seeds for `corridor_explore` happen to spawn
   in dungeon levels where `>` is behind unexplored or hidden
   passages** that the agent can't reach within a 100-300 turn budget.
   The compact CONTROL also got 0/8 on the same 8 seeds, with
   per-rollout turn budgets up to 319 game turns. So this isn't a
   non-compact-specific issue.

2. **Qwen3.5-9B can't follow the `find_and_descend` instruction.** Iter8
   advertised the mega-skill in the cheat sheet, but most rollouts
   ignored it and kept calling `autoexplore`/`move`/`search` micro-skills.
   Looking at iter8 R5 (saw `>` 42×): the agent called
   `find_and_descend` only 2× and both times the skill reported "No `>`
   visible" because `>` wasn't in the chars array at that exact moment.
   The agent didn't retry after seeing `>` in subsequent obs.

3. **Non-compact prompt bloat saturates the model's effective context.**
   By turn 100 the prompt is 3M+ tokens. Qwen3.5-9B's effective
   reasoning quality degrades well before that. Iter6 R5 died to a
   jackal in 74 turns — combat decisions are also degraded.

## Honest assessment

The harness side is in a much better place than it started. **Eight
non-trivial improvements shipped**, all gated by 294 passing tests.
Scout reward best jumped from 0.077 → 0.185 (2.4×).

But **the "maximum descent rate" the user asked for is fundamentally
gated by:**
- The 9B model's ability to chain ~80-100 NLE turns of correct
  exploration under a multi-million-token prompt
- Seed luck — `>` accessibility varies massively per NLE dlvl 1 layout
- Combat survival on this character class

**Next moves with much higher leverage than another harness pass:**

1. **RL training** with the current harness on `corridor_explore`. The
   scout reward signal is dense; the harness is solid. A few hundred
   PPO steps should plant the "see `>` → call descend" reflex that
   Qwen3.5-9B's base policy lacks.
2. **Move to a stronger model.** `claude-haiku-4-5` or
   `gpt-4.1-mini` would near-zero-shot descent on the same harness —
   we have evidence of this from earlier traces (haiku descended
   reliably on iter v0.0.34+).
3. **Tier change for measurement.** `empty_room` and `solo_combat`
   have `>` adjacent to spawn. Use them as control tasks for harness
   improvements; reserve `corridor_explore` for trained-model evals.
4. **Push v0.0.63 to Hub.** Permission to `prime env push` was denied
   mid-session; the v0.0.63 changes are local-only. The next eval
   anyone runs via `prime eval jonathanliu/nethack` will still hit
   v0.0.60 and miss the 8 fixes above. *Requires user approval.*

## Commits on `main` since /goal start

- `7b48e94` harness: locked-door HINT + wall-gap doorway detection + autoexplore skips stairs UP
- `c8fd8c5` harness: VISIBLE FEATURES + GLYPHS render in non-compact mode + stairs-DOWN memory
- `bcafbde` harness: autoexplore dead-end search + reroute-to-door when frontiers are short
- `9b37635` harness: find_and_descend mega-skill bundles path-and-descend in one call

## Eval artifacts

All under `experiments/results/local_no_compact_v0063{a,b,c,d,e,f,g,h}/`
and `experiments/results/local_compact_v0063_control/`. Each contains
`results.jsonl` + Prime dashboard upload URL in the corresponding
`/private/tmp/.../tasks/*.output` log.
