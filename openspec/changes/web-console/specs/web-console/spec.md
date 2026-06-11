## ADDED Requirements

### Requirement: Multi-page console with a landing page
The web console SHALL be a multi-page browser app served by one Flask process over a single `EngineEnv`, sharing one retro stylesheet (gray dungeon tiles, pastel highlight accents). The root path `/` SHALL be a landing page — a description/README of the console and engine capabilities, the embedded knob-effect GIFs, and navigation into the three pages — and SHALL NOT itself contain game controls.

#### Scenario: Landing page is the front door
- **WHEN** a user opens `/`
- **THEN** they see a description of the console + the knob GIFs + links to Map Viewer, Observation Creator, and Tracer, and no live game widgets

#### Scenario: Pages are navigable
- **WHEN** a user follows a nav link
- **THEN** they land on `/map`, `/obs`, or `/traces` respectively, each rendered with the shared theme

### Requirement: Map Viewer page
`/map` SHALL provide live interactive play on the fork engine: the structured map (chars + colors) + message + status, keyboard NetHack commands, and the difficulty/generation knobs grouped into Vision / Stat-based / Dungeon & spawns with boolean toggle switches and numeric slider-plus-editable-field controls. Live knobs SHALL apply on the next step; reset knobs (`room_density`, `monster_difficulty_scale`) SHALL stage and apply on Reset, which regenerates the level.

#### Scenario: Play and tune
- **WHEN** a user types movement keys and adjusts a live knob on `/map`
- **THEN** the hero moves and the live knob takes effect without a reset, while a reset knob applies on the next Reset

### Requirement: Observation Creator page
`/obs` SHALL let a user configure a reproducible observation/scenario (seed + generation knobs + reveal), regenerate, optionally step to a target state, and export it (the observation as JSON and/or a snapshot handle plus the seed/tune config) for reuse as a starting point.

#### Scenario: Create and export an observation
- **WHEN** a user sets a seed + knobs, regenerates, and clicks export on `/obs`
- **THEN** the console returns a reusable representation of that observation/scenario (obs JSON and/or snapshot + config)

### Requirement: Tracer page
`/traces` SHALL list available `.ndjson` rollouts, provide a scrubber over a selected rollout's turns, and render each turn's map + status + reward + game messages + any LLM user/assistant/tool_call panes. Live play recorded from the Map Viewer SHALL be replayable here.

#### Scenario: Replay a recorded rollout
- **WHEN** a user selects a rollout and drags the scrubber
- **THEN** the map and per-turn fields update to that turn

### Requirement: Vision changes re-render in both directions
Changing any vision knob (`vision_radius`, `fog_of_war`, `reveal_map`) live SHALL force the rendered observation to update immediately to reflect the new setting — including when visibility is REDUCED (radius down, fog on, reveal off) — not only when visibility is increased.

#### Scenario: Reducing reveal updates the view
- **WHEN** a user turns `reveal_map` off (or lowers `vision_radius`) on `/map` without taking a game action
- **THEN** the rendered map updates to the reduced-vision view rather than leaving the previously revealed cells on screen
