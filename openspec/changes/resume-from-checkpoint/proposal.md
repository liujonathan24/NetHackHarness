## Why
The checkpoint story (save/load levels, snapshot/branch, state modification) is missing its capstone: loading a recorded game, picking a step in the Tracer, and jumping back into live play in the Map Viewer. Full per-step snapshots can't persist to disk (the arena is an ASLR mmap with live pointers), and the game isn't deterministic enough to replay by seed+actions (mobs). The pointer-safe path is to checkpoint at floor entry as { seed, level blob, player blob } and reload, re-randomizing mobs (good for Monte-Carlo; exact mob reproduction is not a goal).

## What Changes
- **Fork C**: `nle_save_player`/`nle_load_player` — serialize the hero (full `savegamestate`: u struct + inventory + attributes + dungeon graph) to a pointer-safe blob and restore it onto an already-loaded level. (Spike-proven.)
- **Binding**: `EngineEnv.save_player(path)`/`load_player(path)`; a `checkpoint(path)`/`resume(path)` helper that bundles seed + level blob + player blob.
- **Recording**: the Map Viewer Record writes a floor-entry checkpoint (seed + level.blob + player.blob) each time dungeon depth changes, referenced from the `.ndjson`.
- **Tracer**: a "Resume from here" action on a selected step → loads the nearest floor-entry checkpoint into the Map Viewer.
- **Map Viewer**: resume = `reset(seed)` (same seed → object appearances match) → `load_level` → `load_player` → live play. Mobs re-randomize.

## Capabilities
### New Capabilities
- `checkpoint-resume`: floor-entry checkpoints (level + player blobs) + Tracer→Map-Viewer resume.

### Modified Capabilities
- `nethack-engine`: adds player-state serialization (`save_player`/`load_player`).

## Impact
- Fork C: `save.c`/`restore.c`/`nle.h` (player serializer) → submodule bump.
- `nethack_core/_engine.py`,`engine_env.py` (binding); `tools/play_server.py` (recording + resume endpoints + Tracer/Map Viewer UI).
- Forward-only: new recordings carry checkpoints; old display-only recordings stay view-only.
