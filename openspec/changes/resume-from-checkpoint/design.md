## Approach
Snapshots can't persist to disk (arena is ASLR mmap with live pointers), and play isn't deterministic enough to replay (mobs). So a checkpoint = pointer-safe `savelev` level blob + `savegamestate` player blob + the seed. Resume = `reset(seed)` (so object appearances/ids shuffle identically) → load level → load player → render. Mobs re-randomize, which is desirable for Monte-Carlo.

## Decisions
- **Floor-entry granularity**: checkpoints on depth change; any selected step resumes from its floor's entry checkpoint. Keeps recordings small and gives natural save points.
- **Load ordering**: level before player (restgamestate relinks ustuck/usteed + worn ball/chain against the current level's chains).
- **Two-phase render**: load_*_raw mutate without rendering; one step after both repaints (rendering inside the C call jumps a dead fcontext → SIGSEGV).
- **Seed in the checkpoint**: resolves the per-game object-appearance shuffle and id counters without serializing the identification tables.

## Known limitation (follow-up)
Cross-process resume (after a server restart) needs all dungeon level files bundled into the checkpoint, not just the current floor — the player's dungeon graph references off-floor levels whose files are absent in a fresh process. In-session resume works. Fix: extend `checkpoint`/`resume` to bundle/restore every `<lock>.<n>` (reuse the snapshot path's `nle_fr_bundle_levelfiles`).
