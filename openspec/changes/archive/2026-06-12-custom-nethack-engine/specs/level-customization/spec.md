## ADDED Requirements

### Requirement: Custom level loading
The engine SHALL expose `nle_load_level` to load a custom level/scenario (a NetHack `.des` description and/or a struct-prep produced from a difficulty preset), and the harness SHALL invoke it so that a rollout begins on the specified custom level.

#### Scenario: Load a custom des-file level
- **WHEN** a rollout is configured with a custom level description and reset
- **THEN** the game starts on that level with the described layout, monsters, and features

#### Scenario: Invalid level description rejected
- **WHEN** a malformed level description is supplied
- **THEN** loading fails with a clear error before the rollout starts, not mid-game

### Requirement: Curriculum tiers migrate off MiniHack
Curriculum tiers that currently depend on MiniHack `des_file`s SHALL be re-expressed through `nle_load_level` (or snapshot-based presets), and the MiniHack git dependency SHALL be removed once parity is reached.

#### Scenario: Existing tier runs without MiniHack
- **WHEN** a tier that previously required MiniHack is run after migration in an environment without MiniHack installed
- **THEN** the tier loads its level and runs to its success criterion as before

#### Scenario: MiniHack dependency removed
- **WHEN** project dependencies are inspected after curriculum migration
- **THEN** the MiniHack git dependency is absent and no tier imports it

### Requirement: Preset = snapshot equivalence
A difficulty/level preset expressed as a saved snapshot SHALL load by restoring that snapshot, and loading it MUST yield a reproducible starting state across rollouts.

#### Scenario: Preset restores identical start
- **WHEN** the same preset snapshot is loaded at the start of multiple rollouts
- **THEN** each rollout begins from a byte-identical starting observation
