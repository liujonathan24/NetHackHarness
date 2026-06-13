# Go-Explore

"First return, then explore" (Ecoffet et al. 2021), adapted to NetHack using the
engine's **in-memory snapshot/restore/branch** API.

## Idea
Classic exploration fails because the agent forgets promising states. Go-Explore:
1. **Archive** interesting states (keyed by a cell descriptor — here: dungeon
   level + coarse position / progress).
2. **Return** to a promising archived state *deterministically* — via
   `EngineEnv.snapshot()` / `restore(handle)` (byte-exact restore; no replay
   needed) — instead of re-playing from scratch.
3. **Explore** from there (random/biased actions or a short LLM rollout); archive
   any new cells reached; repeat. Keep the best trajectory to each cell.

## What's here
- **`core.py`** — the Monte-Carlo lookahead/branch primitive: `mc_lookahead`
  snapshots the live state, branches candidate actions (reseed-after-restore so
  chance diverges), scores by depth-gain/death, ranks them; `replay_then_branch`
  returns to a point and branches continuations. This is the **return+explore**
  engine of Go-Explore.
- **`demo.py`** — `python -m approaches.go_explore.demo` shows ranked candidate
  actions from a live state.

## Status
Primitive implemented (snapshot/branch verified byte-exact). Planned driver:
`python -m approaches.go_explore.go_explore` — the full archive→return→explore
loop over `core.mc_lookahead`, writing an NDJSON trace + the cell archive.

## Maps onto this repo
- Return = `nethack_core/engine_env.py` `snapshot`/`restore`/`branch` (the fork's
  `nle_fr_snapshot` was fixed to be byte-exact incl. repeated restores).
- Cell key / score = dungeon level (`blstats[12]`) + position (`blstats[0,1]`).
- Knowledge (optional, for biased exploration) = the shared `wiki/` snapshot.
