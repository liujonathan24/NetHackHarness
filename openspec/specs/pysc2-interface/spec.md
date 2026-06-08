## ADDED Requirements

### Requirement: Typed observation spec

The interface SHALL provide a typed structured observation, built on the
canonical map model, exposing the player position, the typed entity list (with
coordinates and per-kind attributes), the compact grid, and the status,
inventory, and character blocks as declared feature layers (each with a typed
schema). It SHALL be derived from `nethack_core` (`build_map_model` +
`StructuredObservation`), not re-parsed from raw NLE.

#### Scenario: Observation carries the map model + status/inventory
- **WHEN** an observation is produced for a turn
- **THEN** it exposes the player position, the entity list with coordinates, the grid, and the status / inventory / character blocks

#### Scenario: Observation has a declared schema
- **WHEN** the observation spec is queried
- **THEN** it reports the typed shape of each feature layer (field names/types), independent of any particular turn

### Requirement: Typed action spec

The interface SHALL provide a typed action set derived from the schema'd skill
registry (so it cannot drift from the real actions) covering at least the core
actions (move, attack, descend, search, pickup, move_to), each with typed
arguments, plus a raw NLE action-index escape hatch.

#### Scenario: Core actions are typed, derived from the registry
- **WHEN** the action spec is queried
- **THEN** it lists the core actions with their argument schemas, sourced from the skill registry (not a hand-maintained duplicate)

#### Scenario: Raw action escape hatch
- **WHEN** an agent needs an action outside the typed set
- **THEN** it can submit a raw NLE action index accepted by the underlying env

### Requirement: Typed env wrapper

The interface SHALL provide a thin env wrapper over `NetHackCoreEnv` exposing
`reset() -> Observation` and `step(action) -> (Observation, reward, done, info)`,
returning the typed observation and accepting a typed or raw action. Typed
actions SHALL execute via the existing skill dispatch (behavioral parity with the
harness); raw actions via `NetHackCoreEnv.step`. Existing core behavior
(seeding, stepping) SHALL be reused, not reimplemented.

#### Scenario: Reset returns a typed observation
- **WHEN** the wrapper is reset
- **THEN** it returns a typed observation built from the core env's initial state

#### Scenario: Step applies a typed action via skill dispatch
- **WHEN** a typed action is passed to step
- **THEN** the wrapper executes it through the same skill dispatch the harness uses and returns the next typed observation, reward, done, and info

#### Scenario: Reuses the core env
- **WHEN** the wrapper steps or resets
- **THEN** it delegates to `NetHackCoreEnv` (no reimplementation of NLE stepping/seeding)
