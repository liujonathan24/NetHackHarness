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

### Requirement: Curriculum runs without MiniHack
The curriculum tiers SHALL run with `minihack` removed. The static des tiers (`empty_room`, `solo_combat`, `multi_combat`) SHALL be compiled once to level-file blobs (des → `lev_comp` → instantiate → save) and loaded via `load_level`; the native-generation tiers SHALL use the engine's generation directly.

#### Scenario: Migrated tiers load and play (behavioral smoke)
- **WHEN** each migrated curriculum tier is loaded
- **THEN** it presents the specified features (a downstair, the specified monsters/room) and a short rollout runs to completion — verified without `minihack` installed
