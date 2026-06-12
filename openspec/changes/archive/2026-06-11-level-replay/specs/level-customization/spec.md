# level-customization (delta — level-replay)

## ADDED Requirements

### Requirement: Generate, save, and load floor blobs
The engine SHALL let a caller generate floors natively (seed + generation knobs), save the current floor to a portable level-file blob, and start a session on a saved floor. The blob format SHALL be NetHack's concrete `savelev`/`getlev` level file. The binding SHALL expose `nle_save_level`/`nle_load_level`; `EngineEnv` SHALL expose `save_level(path)`/`load_level(path)` against a floor-library directory.

#### Scenario: Save/load round-trip
- **WHEN** a floor is generated, saved via `save_level(path)`, then loaded into a fresh session via `load_level(path)`
- **THEN** the loaded floor's observation grid matches the saved floor and play proceeds normally

#### Scenario: Generate an arbitrary number of floors
- **WHEN** floors are generated across varying seeds/knobs and saved
- **THEN** distinct floor blobs are produced and each reloads to its saved layout

### Requirement: MiniHack is removed
The MiniHack mini-task curriculum tiers SHALL be removed (not migrated), and the `minihack` git dependency SHALL be dropped from all `pyproject.toml`/lockfiles. Native-generation tiers and saved-level blobs remain the level sources.

#### Scenario: Curriculum runs without MiniHack
- **WHEN** the curriculum is exercised with `minihack` uninstalled
- **THEN** it runs using native generation and/or saved-level blobs, importing no `minihack`

### Requirement: Secure state checkpoint + modification
On top of snapshot/restore and save/load, the engine SHALL provide a curated, validated state-modification API. `EngineEnv.modify(**changes)` SHALL apply a whitelisted set of mutations — `hp`, `max_hp`, `goto_depth`, `gold`, `xp_level`, `hunger` — both live and via an at-reset config. Unknown fields and out-of-range values SHALL be rejected (no arbitrary memory writes).

#### Scenario: Apply a field mutation
- **WHEN** `modify(hp=20)` (or `gold`/`xp_level`/`hunger`) is applied
- **THEN** the corresponding `blstats` field reflects the new value on the next observation

#### Scenario: Skip dungeon levels
- **WHEN** `modify(goto_depth=4)` is applied from dungeon level 2
- **THEN** the hero is on dungeon level 4 (the depth blstat reads 4) on a valid floor

#### Scenario: Reject unsafe modifications
- **WHEN** an unknown field or an out-of-range value is passed to `modify`
- **THEN** it is rejected with an error and the game state is unchanged

#### Scenario: At-reset modification config
- **WHEN** a modification config is supplied at `reset`
- **THEN** the episode starts with those mutations applied
