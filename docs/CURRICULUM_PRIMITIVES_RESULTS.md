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
