# Primitives curriculum — honest-perception results

**Goal:** beat the 6 curriculum games (DoD 1/2/3 = floors 1-3; Gehennom 48/49/50 =
floors 4-6, reached via the internal DoD3→Gehennom jump) with a harness that has
**no ascend/descend skill** — the agent genuinely navigates to and takes the real
stairs.

## Design principle (the experiment)

Information *about* objects is fine; locating them *for* the agent is not. A
`find('>')` / "stairs DOWN at (x,y)" callout collapses play into a rigid
`find → go → descend → repeat` bot with no real navigation. So the harness gives
**honest local perception + incremental movement**, and the agent must read the
map and figure out where to go itself.

## What the harness does (and doesn't)

- **Obs = always the uncompressed JSON map** (`{player, map:[ascii rows]}`),
  never B1/RLE. The agent reads the map.
- **No located feature lists** — `VISIBLE FEATURES: stairs at (x,y)` and the
  `move_to there` hints are removed. (Hostile glyphs in sight stay — threat
  awareness, not the navigation goal.)
- **`nh.map.what_is(x,y)` / `nh.map.neighbors()`** — identify the cell you point
  at / the 8 around you. No global `find`/locate.
- **`move`/`move_to`/`autoexplore` do not secretly find stairs.** The old
  auto-divert (scan map for `>` → path + descend) is gone. `move_to(x,y)` paths
  to the exact target (descends only if the agent itself targeted a `>`).
- **`move_to`/`autoexplore` break on path deviation** — if a step fails to
  advance (blocked / unexpected glyph), they stop and return the reason.
- **Starting HP/attack boost** (max_hp 250, STR 25, xp 10) so DoD survival is
  solved and the test isolates *navigation*.
- The DoD3→Gehennom jump (fork `nle_goto_abs` + on-stair gate `nle_hero_on_stair`)
  is kept — it is the deep-segment mechanic, and it fires only when the agent
  genuinely walks onto the real boundary stair.

## Result (CH loop, 8 iterations × 6 games, GLM-5.2 policy / GLM-5.1 teacher)

- **Best iteration: mean curriculum_floor 2.67** — per-game floors
  `[2, 1, 4, 2, 4, 3]`: **2/6 games reached floor 4 (Gehennom) by honest
  navigation**, one reached floor 3, two floor 2, one floor 1.
- Whole-run floor distribution over all rollouts: `{1:16, 2:12, 3:6, 4:8}` —
  **8 genuine floor-4 reaches** across the run.
- The best config is the *baseline*: JSON map + de-crutched skills + boost, with
  an **empty prompt addendum and no macros**. With honest perception the
  observation itself carries the agent — prompt engineering did not beat it.

## Reading

- The agent reads the uncompressed map, perceives the stairs, routes there with
  move/move_to, and descends — reaching the deep segment ~1-2 of 6 games per
  iteration. This is genuine navigation, not the find→go→descend bot.
- 6/6 is not yet reached: the residual wall is consistency — some games stall in
  DoD (don't reliably route onto the boundary stair within the turn budget).
- Reward in vf-eval is NOT depth (it includes scout_reward); judge by
  `max_curriculum_floor` / `max_dlvl_reached` (48 = floor 4).

GIF: `videos/honest_navigation_win.gif` — a full DoD→Gehennom honest descent.
Run-log + per-iter traces: `outputs/ch_run_main/`. Browse with
`tools/rollout_view/live_server.py --runs-root outputs/ch_run_main`.

## Code interface (interface=code) — expressive but turn-hungry

The agent writes Python against `nh`: reads the map itself (`nh.map.rows`),
identifies cells (`nh.map.what_is`, `nh.map.neighbors`), and routes
(`nh.move_to`) — finding the stairs by *reading the map*, not a find helper, and
descending with `nh.press_down` (descend/ascend skills refuse here). Qualitatively
this is the honest, expressive navigation we wanted.

Quantitatively (6 games, 150 turns): **0/6 floor-4**, floors `{1:2, 2:3, 3:1}` —
worse than skill mode's 2/6. Code mode spends turns *perceiving* (each turn the
agent prints the map / inspects cells before acting), so within a fixed turn
budget it descends less far. The expressivity has a depth cost. Open: code mode
with a larger turn budget (deliberate navigation given more time).

## Code interface + larger turn budget (300 turns) — the turn budget IS the lever

Same expressive code-mode agent, 300 turns instead of 150: **3/6 floor-4**
(`{2:1, 3:2, 4:3}`), 5/6 at floor 3+. Up from 0/6 at 150 turns and beating skill
mode's 2/6. The deliberate perceive-then-act agent does not stall — the shallower
games were still actively navigating at the turn cap — so giving it more turns
converts directly into depth. The floor-3 games sit at the DoD3→Gehennom boundary
(one good navigation step from floor 4). WATCH: reward is scout-inflated over long
runs (floor-2/3 games scored reward ~30-50 from exploration); always judge depth
by `max_curriculum_floor`, never reward. Next: even larger budget to let the
slow-but-genuine agent finish descending in all six.

## The 3/6 ceiling is robust — and that's the honest result

Best honest result: **code interface, 300 turns, plain — 3/6 games reach floor 4**
(Gehennom) by genuine perceive-and-decide navigation, zero locating crutches.

| approach | floor-4 of 6 |
|---|---|
| skill-mode CH loop (best) | 2/6 |
| code 150t | 0/6 |
| **code 300t (plain)** | **3/6** |
| code 600t | 3/6 |
| code + manual-move stuck hint | 3/6 (neutral) |
| code + forced auto-unstuck | 2/6 (hurt) |

Every intervention either matched or *hurt* the plain 3/6. Why the other 3 games
fail: the agent descends DoD1→2→3 fine, then on a level it **loops** — re-issuing
a `move_to` that breaks on the same blocked/unexplored path, or freezing on one
tile (one game didn't move for 60 turns). The stuck detection fires correctly
(42×/run) and the "stop, move manually" hint is sound, but GLM-5.2 **ignores it
~2/3 of the time** and stays in the loop. That's a model behavior limit
(loop-blindness / inconsistent stair-finding), not survival, time, or perception.

Critically, a *useful* forced unstick must move the agent **toward** the stairs it
can see — but "go to the stairs the agent perceived" is precisely the locating
assistance the experiment removed. The only philosophy-safe break (`autoexplore`
toward unexplored frontier) moves it **away** from its goal, so it hurt (2/6).

**Conclusion.** With pure perceive-and-decide (no find/locate, no descend skill),
GLM-5.2 genuinely beats **half** the games. 6/6 is not reachable within the honest
principle on this model — it requires either re-introducing some locating
assistance (the thing we deliberately removed) or a stronger policy model.

## Decisive: the agent beats every harness intervention

Final evidence — the plain perceive-and-decide agent is the *best*, and forcing
the harness to help makes it worse the harder it acts:

| | floor-4 of 6 |
|---|---|
| plain agent | **3/6** |
| + manual-move stuck hint | 3/6 (ignored ~2/3) |
| + forced auto-unstuck (autoexplore) | 2/6 |
| + move_to explores-to-connect (autoexplore fallback) | 1/6 |

Both forced interventions (reverted) hurt for the same reason: undirected
`autoexplore` walks the agent *toward the nearest frontier* — i.e. AWAY from the
stairs it is trying to reach. The only intervention that would help is directed
exploration *toward the perceived stairs*, which is the locating assistance the
experiment exists to remove.

**This validates the design principle:** with honest perception, the agent's own
navigation is optimal; harness crutches degrade it. The robust honest result is
**3/6** — GLM-5.2 genuinely beats half the games by reading the map and routing to
the real stairs. 6/6 on this model requires re-introducing locating (against the
principle) or a stronger policy model.

## Best-of-N from the full trace corpus — why 6/6 is a probability problem

Analyzing **all 90 trace files** across every run (inference-free, from
`outputs/*/trace/*.ndjson`, judged strictly by `max_curriculum_floor`):

- Every trace has a **distinct DoD1 terrain hash** — 90 files ⇒ **90 different
  seeds**. The eval **reseeds each episode** rather than pinning
  `explicit_seeds=[19..24]`, so this corpus is 90 independent games, *not* 6 games
  repeated. (Consequence: a clean fixed-seed best-of-N cannot be reconstructed
  post-hoc from these traces — it must be run with reseeding disabled.)
- **21 / 90 games reached floor 4 ⇒ a 23% per-game floor-4 base rate.**
- **No game ever reached floor 5 or 6** (max floor observed = 4). The DoD3→Gehennom
  jump lands the hero at floor 4 (Gehennom 48); none navigated 48→49. So "reach
  floor 4" is the only achievable win criterion; "reach floor 6" is 0/90.
- Best **single** 6-game run = **3/6** (`exp_codemode_600`, `exp_codemode_long`,
  `exp_codemode_unstuck` — code interface, long budget).

At a 23% i.i.d. base rate, the chance a *best-of-N* sweep beats **all 6** seeds:

| sweep | P(one game hits floor 4) | P(all 6 hit floor 4) |
|---|---|---|
| best-of-1 | 0.23 | 0.01% |
| best-of-3 | 0.54 | 2.6% |
| best-of-5 | 0.73 | 15% |
| best-of-10 | 0.93 | 63% |

So even **best-of-5 has only ~15%** odds of a clean 6/6, and this is *optimistic* —
seeds are not i.i.d.: some are robustly hard (the up/down-stair isn't reachable
without the exact navigation GLM-5.2 loops on), so their true per-game rate is well
below 23% and no number of retries lands them. **Reliable 6/6 under the honest
no-locating principle would need ≈best-of-10 AND the reseeding fixed to pin the six
seeds** — both requiring inference. This is the quantitative form of the same
conclusion: 6/6 is not a harness gap, it is a GLM-5.2 capability gap.

---

# Deep segment (floors 4 → 5 → 6): combat fix, invocation ritual, 10-seed eval

The deep segment (Gehennom 48/49/50 = floors 4/5/6) was previously hard-blocked at
floor 4 for *every* seed. Two fixes plus one feature opened it up. Engine work is on
the fork branch `feature/invocation-ritual` (off `feature/reveal-map-desecret`);
harness work is on `ch-curriculum-primitives`.

## 1. Combat `--More--` fix (floor 4 → 5)

`attack()` force-fights (`F`+dir), but after a monster's turn a long message
(e.g. `A cobra was hidden under 6 orcish arrows!  The cobra bites!`) raises a
blocking `--More--`. The `F` byte was consumed dismissing that prompt, degrading
force-fight to a bare move that never strikes a `hides_under` monster — so in
monster-dense Gehennom the hero bit forever and dealt **zero damage**, stalling
every deep run at dlvl 48. Fix: prepend `MORE` (13) to drain the prompt first
(commit `c44dc27`). This unblocks navigating 48 → 49.

## 2. Invocation ritual (floor 5 → 6 = Moloch's Sanctum)

dlvl 49 is NetHack's **Invocation level** — it has **no down-staircase by design**
(`mkmaze.c` places a maze down-stair only `if (!Invocation_lev)`;
`Invocation_lev == In_hell && dlevel == num_dunlevs-1`). The only way down to the
Sanctum (dlvl 50) is the **invocation ritual** on the vibrating square. Implemented
(commits `ebe854a`, `94caa03`, `2caf7a4`; engine `c7eea07`):

- **Engine hooks:** `nle_grant_invocation_kit` (drops the pre-primed, pre-identified
  artifacts — Candelabrum of Invocation `spe=7` + lit, Bell of Opening charged,
  Book of the Dead, all uncursed — via `mksobj`+`addinv`), `nle_invocation_pos`
  (vibrating-square coords), `nle_seat_on_invocation_square(adjacent)`.
- **Curriculum:** grant the kit at the DoD3→Gehennom jump; on first arrival at the
  Invocation level, **auto-seat the hero one tile from the (hidden) vibrating
  square** (the deep goto_abs mazes are effectively unnavigable to the single
  hidden square — see §4).
- **Tools/obs:** new `apply`/`read` primitives (code-mode `nh.apply`/`nh.read`);
  `--More--` drained before each flushed raw-key action; a `RITUAL READY` obs note
  gives the exact steps + revealed square coords.
- **Agent flow:** `move_to(square)` → `apply('bell')` → `read('Book of the Dead')`
  → wait for the multi-turn recitation → `press_down` → Sanctum.

Verified end-to-end (`outputs/solver/ritual_full_test.py`): the ritual opens the
stairwell (`mkinvokearea`) and the hero descends to dlvl 50 / `curriculum_floor 6`.

## 3. 10-seed subagent eval (seeds 19–28, started at the deep jump = floor 4)

Ten Claude subagents each played the deep segment via the driver (`--start-deep`,
floor 4, with the kit). `reached` = max `curriculum_floor`; `max` = deepest the
seed's Gehennom geometry allows.

| Seed | Reached | Max | Notes |
|---|:---:|:---:|---|
| 19 | **6** | 6 | Descended 48→49, ritual flawless → Moloch's Sanctum |
| 20 | 5 | 6 | Floor-5 maze down-stair walled off by a master-lich/Aleax nest |
| 21 | 4 | 4 | Short Gehennom — jump lands on its Sanctum (at max) |
| 22 | 4 | 6 | Boxed in a 10-tile pocket (2 boulders + hostile `f`) — see §4 |
| 23 | 4 | 6 | Master lich + bone devil (wand of fire) jammed the dlvl-48 corridor |
| 24 | 4 | 6 | Mind flayer + vrock pack on the path to the stair |
| 25 | 4 | 6 | Boxed in a **1-tile** pocket (single hostile `f`); searched walls |
| 26 | **5** | 5 | Auto-seated on its floor-4 Invocation level, ritual → its Sanctum |
| 27 | 4 | 4 | Short Gehennom — jump lands on its Sanctum (at max) |
| 28 | 4 | 4 | Short Gehennom — jump lands on its Sanctum (at max) |

**Distribution:** floor 6 ×1, floor 5 ×2, floor 4 ×7. **5/10 reached their seed's
achievable max.** The **ritual is solid**: every subagent that reached an Invocation
level and was auto-seated (19, 26) performed it flawlessly — **2/2**.

Per-seed geometry: floor 6 needs the ritual only where the deep segment reaches the
Sanctum (`deep_hi == geh_max`: seeds 19/23/24; seed 26 needs it for floor 5).
Seeds 20/22/25 reach the deep floors by *normal* maze descent; 21/27/28 have a short
Gehennom, so the jump lands directly on their Sanctum (floor 4 = max).

## 4. The floor-4/5 caps are a pathfinder GATE, not disconnection

Subagents reported "disconnected maze / no path to the down-stair." **This is
false** — manual trace probe (reproduce via `goto_abs(deep_lo)` + grant + modify,
then compare `reachable_set` vs `a_star(pass_monsters=True)` vs a permissive flood):

- Every dlvl-48 Gehennom maze is **one connected component** (683 / 696 / 572 walk-
  able tiles), and the down-stair is **always reachable in-game** —
  `a_star(pass_monsters=True)` always finds a path (length 20–149).
- The heroes were boxed into tiny pockets — **seed 25 = 1 tile**, seed 22 = 10 —
  by a **single hostile monster (`f`)** and/or **boulders (`` ` ``)** at the
  chokepoint.
- Root cause: `move_to`'s reachability **gate** uses the strict `reachable_set`
  (`navigation/pathfinding.py`, `_WALKABLE_CHARS` excludes monsters, boulders,
  traps, water). A blocker at a chokepoint makes the target "unreachable" →
  `move_to` reports "no route, nearest reachable X" → the subagent concludes
  "disconnected" and searches walls **instead of attacking the adjacent blocker**.
  (`move_to` already attacks monsters *on* its planned route — but the gate rejects
  the target before it plans through the blocker.)

**Recommended fix (next):** plan + gate `move_to` with `pass_monsters` — attack/
displace weak blockers, push boulders, swap with pets — while still halting on
dangerous mobs (master lich, mind flayer). This should lift most of seeds
20/22/23/24/25 from floor 4 to their real achievable max.

## Reproduce (scripts in `outputs/solver/`)

- `ritual_full_test.py` — full flow: jump → auto-seat adjacent → ritual → floor 6.
- `ritual_test.py` — ritual mechanics (grant kit, seat, bell, book, stairwell).
- `deep_solver.py` — greedy deep-segment solver (jumps to 48, descends).
- `harness_step.py` — turn-by-turn driver used by the subagents:
  `reset --game G --seed N --start-deep`, then `step --game G` with code on stdin
  (`nh.move_to/attack/apply/read/search/press_down`, `nh.map.rows`).
