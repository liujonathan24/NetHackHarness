# Onboarding docs

One doc per shipped fix. Each doc:

- Explains the problem the fix solves
- Shows the before/after code (just enough to orient)
- Documents the load-bearing edge cases
- Lists the tests that protect the fix
- Flags future work

Read in order if you're new to the project:

1. [`01-seeding-and-nethackscore.md`](01-seeding-and-nethackscore.md) — why
   the env wraps `NetHackScore-v0` instead of `NetHackChallenge-v0`, and what
   reproducibility means here.
2. [`02-scout-reward-delta.md`](02-scout-reward-delta.md) — the cumulative→delta
   fix on the scout shaping signal.
3. [`03-menu-region-masking.md`](03-menu-region-masking.md) — how the dungeon
   view stops getting polluted with menu text.
4. [`04-bootstrap-character.md`](04-bootstrap-character.md) — role/race/align
   from the welcome line, no extra turn.
5. [`05-terminal-outcome-detection.md`](05-terminal-outcome-detection.md) —
   death vs ascension from the tty, so `ascension_reward` can actually fire.
6. [`06-journal-skill.md`](06-journal-skill.md) — structured agent memory
   (add_note / recall / pin_objective), the Pokemon-bench lesson.
7. [`07-milestones.md`](07-milestones.md) — Pokemon-route-style intrinsic
   termination predicates (Mine Town, Sokoban, Oracle).
8. [`08-pathfinding-and-autoexplore.md`](08-pathfinding-and-autoexplore.md) —
   A* on the glyph grid + frontier autoexplore, the biggest agent UX win.
9. [`09-replay-viewer.md`](09-replay-viewer.md) — the single-file HTML
   trajectory viewer (the Monday demo artifact).
10. [`10-profiling-hot-path.md`](10-profiling-hot-path.md) — Day-3 layer-1
    microbenchmarks: where the time goes and what's worth optimizing.
11. [`11-pufferlib-adapter.md`](11-pufferlib-adapter.md) — gymnasium adapter
    for the non-LM RL audience; ~10× speedup path via PufferLib shmem vec.
12. [`12-wiki-tool.md`](12-wiki-tool.md) — `wiki_lookup` + `wiki_search`
    skills over a substring index (ChromaDB-swap-ready).
13. [`13-code-mode.md`](13-code-mode.md) — sandboxed Python execution
    (Track B), wired end-to-end with sub-LM API stubs.
14. [`14-dynamic-subgoals.md`](14-dynamic-subgoals.md) — LLM-proposed
    curriculum (the autoresearch axis); compiles a structured subgoal
    into a per-rollout termination predicate.
15. [`15-compaction.md`](15-compaction.md) — observation + history compaction
    (v0.0.17–24). 89.8% cumulative-token reduction.
16. [`16-balrog-progression.md`](16-balrog-progression.md) — empirical-ish
    P(ascend | DL, XL) as an informational state field (v0.0.26).
17. [`17-trace-driven-format-fixes.md`](17-trace-driven-format-fixes.md) —
    UNDER PLAYER block + GLYPH KEY + descend short-circuit (v0.0.29–30),
    fixes the haiku stair-confusion failure mode.

There's also a sample [`demo_trajectory.json`](demo_trajectory.json) you can
open in `tools/replay_viewer.html` directly.

## Reading order if you're contributing

If you're picking up a TODO:

- Check `experiment_log.md` or the [project plan](../../../../../../../.claude/plans/wiggly-dreaming-bengio.md)
  for the active priority list (it changes weekly).
- Each onboarding doc has a "Future work" section listing follow-ups for that
  specific fix.

## Reading order if you're debugging

- For non-determinism: start with 01.
- For "the agent isn't getting reward when it should": 02.
- For "the model is confused about what's on screen": 03.
- For "the agent doesn't know what character it's playing": 04.
- For "we ascended but didn't get credit": 05.
- For "the agent doesn't remember anything from earlier in the episode": 06.
- For "the rollout never terminates on the curriculum goal": 07.
- For "the agent is wasting turns on individual move keystrokes": 08.
- For "I need to demo a rollout to Alex": 09.
- For "is the env too slow / where's the bottleneck": 10.
- For "I want to use this with PufferLib": 11.
- For "the agent doesn't know NetHack lore": 12.
- For "what does Track B (code mode + RLM) look like": 13.
- For "the model keeps inventing subgoals; how is that wired": 14.
- For "the per-turn prompt is too big; what compaction is on": 15.
- For "BALROG progression score and how it's surfaced": 16.
- For "the model is confused by the obs format — UNDER PLAYER, GLYPH KEY": 17.
- For "the model is wasting 40%+ of turns on menus / `[yn]` prompts": 18.
