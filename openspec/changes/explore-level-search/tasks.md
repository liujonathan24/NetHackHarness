## 1. Persistent per-level search state

- [ ] 1.1 Key the persistent `search_count` (and exploration memory) by the ACTUAL
      dungeon level (blstats DLEVEL/DEPTH), not the per-call `level_idx` — so search
      progress on a floor accumulates correctly across repeated `explore_and_descend`
      calls within a rollout.

## 2. Complete, prioritized hidden-passage search

- [ ] 2.1 Replace the capped/early-bail search: remove the global `search_budget`
      bail; search until every candidate tile is searched to its per-tile cap
      (bounded only by `max_game_steps` + the HP/hunger danger-halt so the LLM keeps
      control and the agent doesn't starve).
- [ ] 2.2 Prioritize search targets NetPlay-style: walkable tiles whose adjacent
      wall borders unexplored stone, scored by door-walled-by-stone + dead-end
      shape, minus `search_count²` (least-searched, most-promising, nearest first).

## 3. Verification

- [ ] 3.1 Unit test: the search target picker prefers unsearched door/dead-end tiles
      bordering stone and skips exhausted tiles; persistent count keyed by dlvl.
- [ ] 3.2 Real-env test: per-level descent reliability improves vs the capped search
      (more of N fixed seeds reach the downstairs), with no regression to the 7
      baseline test failures.
