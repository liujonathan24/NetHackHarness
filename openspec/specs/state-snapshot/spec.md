## ADDED Requirements

### Requirement: O(1) struct snapshot and restore
The engine SHALL expose `nle_snapshot(ctx) -> bytes` and `nle_restore(ctx, bytes)`, and the harness SHALL surface them as `snapshot() -> bytes` and `restore(bytes)` on the env. A snapshot SHALL capture complete game state such that restoring it yields a game indistinguishable from the snapshotted moment, and the operation SHALL be constant-time with respect to the number of steps taken.

#### Scenario: Round-trip preserves state
- **WHEN** a snapshot is taken, the game is stepped further, and the snapshot is restored
- **THEN** the post-restore observation equals the observation at snapshot time, and subsequent identical actions produce identical observations

#### Scenario: Restore is independent of step count
- **WHEN** snapshot/restore is performed after 10 steps and after 10,000 steps
- **THEN** the operation's cost does not grow with step count (no action re-execution)

### Requirement: Snapshot completeness across dungeon levels
A snapshot SHALL preserve state for all visited dungeon levels, including levels NetHack would otherwise swap to disk, so that restoring after descending and returning reproduces prior levels exactly.

#### Scenario: Multi-level round-trip (spike-gated)
- **WHEN** the player snapshots on level 1, descends to level 3, restores, and re-descends
- **THEN** levels 1–3 match their pre-restore layouts and contents

#### Scenario: Snapshot strategy documented
- **WHEN** the snapshot-completeness spike concludes
- **THEN** the chosen blob strategy (pure ctx memcpy, ctx + bundled on-disk level files, or in-memory levels) is recorded and the API contract above holds regardless of strategy

### Requirement: Snapshot build-compatibility guard
Snapshots SHALL be tagged with a build/struct-version identifier, and `restore` SHALL refuse a snapshot whose identifier does not match the running engine build.

#### Scenario: Mismatched snapshot rejected
- **WHEN** a snapshot produced by a different engine build is restored
- **THEN** `restore` raises a clear version-mismatch error instead of corrupting state

### Requirement: Replay supersedes action-replay
The struct-snapshot mechanism SHALL replace the O(n) action-replay internals in `legacy/replay.py` as the primary replay/branching primitive, while preserving any trajectory-recording surface still consumed by tooling (e.g. the replay viewer).

#### Scenario: Branching via snapshots
- **WHEN** a caller snapshots a state and explores two different action sequences from it by restoring between them
- **THEN** each branch starts from the identical snapshotted state without replaying actions from episode start
