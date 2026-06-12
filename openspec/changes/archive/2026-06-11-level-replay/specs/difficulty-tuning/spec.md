# difficulty-tuning (delta — level-replay)

## ADDED Requirements

### Requirement: Remaining map-generation knobs
The `nle_tune` catalog SHALL include the remaining generation knobs `mob_spawn`, `trap_density`, `locked_door`, `corridor_connectivity`, and `room_size`, each wired to its `mklev`/spawn read-site and applied at level generation (tune-at-start), consistent with the existing `room_density` knob.

#### Scenario: New knobs are settable and safe
- **WHEN** each new generation knob is set (at start) across its range and a floor is generated
- **THEN** the knob round-trips through the tune surface and the floor still generates without crashing

#### Scenario: Visible-effect knobs change the floor
- **WHEN** a knob with an observable effect (e.g. `room_size`) is set away from its default and a fixed seed is generated
- **THEN** the generated floor differs from the default-knob floor in the expected direction (knobs whose effects are off-screen are covered by settability + smoke only)
