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
