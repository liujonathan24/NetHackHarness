# Tasks — resume-from-checkpoint

## 1. Fork C — player serializer
- [x] 1.1 `nle_save_player`/`nle_load_player` (full `savegamestate`/`restgamestate`; pointer-safe; two-phase; load-level-before-player ordering) — fork `2c73561`; spike-proven (Test A in-process + Test B hero-onto-different-level)

## 2. Binding + checkpoint/resume
- [x] 2.1 `RawEngine.save_player`/`load_level_raw`/`load_player_raw` — `32c074e`
- [x] 2.2 `EngineEnv.checkpoint(path)` (seed + level blob + player blob) / `resume(path)` (reset seed → load level → load player → render); seed reproduces appearances/ids — `32c074e`
- [x] 2.3 Tests `test_checkpoint.py` (player round-trip + checkpoint→fresh-env resume→keep playing) — 108 suite green

## 3. Web — record + resume
- [x] 3.1 Record a floor-entry checkpoint on each depth change; every turn references its floor's checkpoint — `effdf0b`
- [x] 3.2 `/resume` endpoint (path allow-listed) + `/current` (live frame, one-shot resume flag) — `effdf0b`
- [x] 3.3 Tracer "▶ Resume from this floor" on checkpointed turns → loads into Map Viewer (no auto-reset clobber) — `effdf0b`

## 4. Verify
- [x] 4.1 End-to-end smoke (record → floor change → resume → keep playing) passes in-session; engine suite green
- [ ] 4.2 KNOWN LIMITATION (follow-up): cross-process resume (load a checkpoint after a server RESTART) SIGSEGVs — the checkpoint bundles the current level + player but not the other dungeon level files the player's dungeon-graph references (the GATE B multilevel bundling). In-session resume (the primary flow) works. Fix = bundle all `<lock>.<n>` level files into the checkpoint (reuse `nle_fr_bundle_levelfiles`) so it's fully disk-portable.
