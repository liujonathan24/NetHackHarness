# Voyager

An automatic-curriculum, **skill-library** agent (after *Voyager: An Open-Ended
Embodied Agent with LLMs*, Wang et al. 2023), adapted to NetHack.

## Idea
Three LLM-driven loops over a growing, persistent skill library:
1. **Automatic curriculum** — propose the next objective appropriate to the
   agent's current state ("reach Mine Town", "identify the unknown potion"),
   biased toward novelty.
2. **Skill synthesis** — write or *compose* a skill that achieves the objective.
   Here a "skill" is an ordered macro over the existing primitive skills
   (`move`, `search`, `descend`, …) — the same `K` (skills) component the
   continual-harness refiner edits — grounded in `wiki/` lookups.
3. **Self-verification** — run the skill in the env; if the objective's success
   predicate holds, add the skill to the library (keyed by name) for reuse;
   otherwise feed the failure back and retry.

## Maps onto this repo
- Skill library = named macros persisted via the env's `bootstrap_dir`
  (`refiner.snapshot_components`/`load_components` already store skills `K`).
- Curriculum = the existing `nethack_harness/curriculum/` tiers/subgoals, driven
  by an LLM proposer instead of a fixed schedule.
- Knowledge = `wiki_lookup` / `wiki_search` (the shared wiki snapshot).
- Knowledge/skills carry across episodes via `bootstrap_dir`.

## Status
Scaffold. Planned entry point: `python -m approaches.voyager.voyager` — runs the
curriculum→synthesize→verify→store loop and writes an NDJSON trace + the grown
skill library.
