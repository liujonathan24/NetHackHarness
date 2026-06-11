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

### Requirement: Observation Creator page (metric composition + plotting)
`/obs` SHALL revive the rollout observation viewer: it SHALL load recorded rollouts, expose the built-in observation/metric series, let a user define a custom metric as a composition of existing series (e.g. `explevel` combined with a dungeon-depth scaling), and plot the resulting series across one or more rollouts. It SHALL reuse `tools/rollout_view` (`series`, `register_custom_metric`, `run_summary`, `aggregate`) and its SVG line-chart rendering rather than reimplementing metrics or plotting.

#### Scenario: Compose and plot a metric
- **WHEN** a user selects rollouts and defines/selects a metric composition on `/obs`
- **THEN** the page plots that metric's series (and built-in series) over turns/rollouts using the rollout_view charts

### Requirement: Tracer page
`/traces` SHALL list available `.ndjson` rollouts, provide a scrubber over a selected rollout's turns, and render each turn's map + status + reward + game messages + any LLM user/assistant/tool_call panes. Live play recorded from the Map Viewer SHALL be replayable here.

#### Scenario: Replay a recorded rollout
- **WHEN** a user selects a rollout and drags the scrubber
- **THEN** the map and per-turn fields update to that turn

### Requirement: Vision overrides are reversible visualization, not game state
`reveal_map` and `fog_of_war` SHALL be implemented as render-time observation overlays — they SHALL NOT mutate the hero's remembered map (`gbuf`) — so toggling them DOWN immediately hides the previously shown terrain, with zero effect on game state or base-game performance (the overlay path is never exercised by normal play). `vision_radius` remains genuine vision (already-remembered cells correctly persist when it is reduced). Changing any vision knob live SHALL re-render the observation immediately in either direction.

#### Scenario: Reducing reveal hides terrain without changing the game
- **WHEN** a user turns `reveal_map` off (or fog on) on `/map` without taking a game action
- **THEN** the rendered map immediately drops back to the genuinely-seen/remembered cells, and the hero's actual remembered map is unchanged (a subsequent normal step behaves as if reveal had never been on)
