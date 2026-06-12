# nethack-engine (delta — level-replay)

## MODIFIED Requirements

### Requirement: The fork engine is the sole backend
The harness SHALL drive NetHack exclusively through the fork `_engine` binding; the `nle` PyPI package SHALL NOT be imported or depended upon. `NetHackCoreEnv.seed/reset/step` SHALL delegate to `EngineEnv`, building `CoreObservation` from the binding buffers, and `observations.py` `shape()` + `StructuredObservation` field/type surface SHALL be unchanged for consumers.

#### Scenario: No nle dependency remains
- **WHEN** the repo is searched for `import nle` / `from nle` / `minihack`
- **THEN** there are no live references outside archived/legacy docs, and `uv sync` resolves with `nle` and `minihack` removed from every `pyproject.toml`/lockfile

#### Scenario: Observation parity across the cutover
- **WHEN** an episode is stepped through the post-cutover `NetHackCoreEnv`
- **THEN** the `StructuredObservation` field names/types/shapes match the pre-cutover contract, and GATE A golden-trace parity + determinism suites stay green

## ADDED Requirements

### Requirement: Snapshot-based divergent exploration
`EngineEnv` SHALL expose `branch(n, reseed=True)` that produces `n` continuations from the current state via snapshot/restore. With `reseed=True` the engine SHALL reseed the RNG after restore so random-chance events (spawns, search, doors) can diverge across branches; with `reseed=False` the branches SHALL be identical to a plain restore. Plain `snapshot()`/`restore()` SHALL remain byte-exact.

#### Scenario: Reseeded branches diverge
- **WHEN** `branch(n, reseed=True)` is called and each continuation steps the same action sequence
- **THEN** the continuations can yield different outcomes (observable variance over K steps), while `reseed=False` continuations are identical

#### Scenario: Plain restore stays exact
- **WHEN** a snapshot is restored without reseeding and stepped
- **THEN** the result is byte-identical to the original timeline (existing snapshot guarantee preserved)
