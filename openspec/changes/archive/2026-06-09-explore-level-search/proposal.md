# explore-level-search

## Why
`explore_and_descend` caps the agent at ~40% per-level descent reliability
(mean max dlvl ~1.4 vs NetPlay's 2.6). The diagnosis
(`docs/netplay-vs-our-harness.md`) shows the #1 cause: our hidden-passage **search
is capped (`search_budget`) and bails (`break`) when no dead-end is found**, so on
~60% of levels the downstairs (often behind a hidden passage) is never discovered.
NetPlay's `explore_level` instead searches an **unbounded-until-exhausted,
prioritized** set of tiles over a **persistent `has_seen` / `search_count` map**,
so it always finds a reachable downstair.

## What
Replace the capped/bail search in `explore_and_descend` with an `explore_level`-style
search over a **persistent per-level map**:
- A persistent (per dungeon level) `has_seen` mask and `search_count` map, kept on
  the env so it survives across `explore_and_descend` calls within a rollout.
- A **prioritized search target**: tiles whose adjacent wall borders unexplored
  stone, scored by NetPlay's heuristic (door-walled-by-stone, dead-ends, minus
  `search_count²`), choosing the nearest highest-priority least-searched tile.
- Search **until the priority set is genuinely exhausted** (every candidate tile
  searched to a per-tile cap), not until an arbitrary global budget — but still
  bounded by the per-call `max_game_steps` and the HP/hunger danger-halt so the LLM
  keeps control and the agent doesn't starve.

## Non-goals
- In-skill combat / `melee_attack` (that's fix #2, a separate change).
- Porting autoascend's full room/corridor graph (we keep the glyph-grid + masks).
