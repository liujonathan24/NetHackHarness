# Comet Design Handoff

- Change: web-console
- Phase: design
- Mode: compact
- Context hash: 11aeac0922c8aef3ec779c86bd22ddc6fffeded84f0ec19220eb5da0680f88cc

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/web-console/proposal.md

- Source: openspec/changes/web-console/proposal.md
- Lines: 1-32
- SHA256: 67363d88b685c62b2b527b4bac1358ed18acabce5749a73cc1541c3dd56f8ee3

```md
## Why

The fork engine is now driven from the browser via `tools/play_server.py` — a single-page Flask app that grew organically into one "cooked" HTML blob mixing a live play view, the difficulty/generation knob controls, an embedded GIF gallery, and a trace replayer. It works but is hard to read, extend, or navigate, and there is no front door: a newcomer lands directly in a play screen with no description of what any of this is.

We want a proper **web console** that is the primary interface (the Textual launchpad is legacy): a retro-styled landing page that explains the project and shows the knob-effect GIFs, plus distinct pages you navigate into for the three real activities — viewing/playing the map, creating observations/scenarios, and inspecting traces.

There is also a concrete bug to fix: the live vision controls (`vision_radius`, `fog_of_war`, `reveal_map`) only re-render when *increasing* visibility (the ctrl-R redraw adds revealed cells). **Reducing** vision does not force the view to update, so turning reveal off / shrinking the radius leaves stale revealed cells on screen until the next real action.

## What Changes

- Replace the single-page `play_server.py` HTML with a **multi-page web app** sharing one retro stylesheet (gray dungeon tiles, pastel highlights):
  - **Landing page** (`/`): README/description of the console + the engine capabilities, the embedded knob-effect GIFs, and links into the three pages. No game controls.
  - **Map Viewer** (`/map`): live interactive play on `EngineEnv` with the grouped difficulty/generation knobs (Vision / Stat-based / Dungeon & spawns), Reset/regenerate, and the live-vision behavior.
  - **Observation Creator** (`/obs`): configure a reproducible game observation/scenario — seed + generation knobs + reveal — regenerate, optionally step to a target state, and export/snapshot it for reuse.
  - **Tracer** (`/traces`): replay recorded `.ndjson` rollouts (scrubber over turns; map + status + reward + messages + LLM panes) and record live play.
- **Fix vision-reduce re-render**: reducing any vision knob (`vision_radius` down, `fog_of_war` on, `reveal_map` off) forces a re-render so the view reflects the reduced setting immediately, not just on the next keystroke.
- Keep the JSON API (`/reset`, `/step`, `/live`, `/set_tune`, `/catalog`, `/record_*`, `/traces`, `/trace`, `/gif*`) — the redesign is presentation/navigation, not a protocol rewrite.

## Capabilities

### New Capabilities
- `web-console`: The browser-based console for the fork engine — a retro-styled landing page plus three navigable pages (Map Viewer, Observation Creator, Tracer), their shared rendering/controls, and the live-vision re-render semantics. This is the primary human interface to the engine.

### Modified Capabilities
<!-- No existing OpenSpec spec covers the web interface; this is the first formal spec for it. The difficulty-tuning / state-snapshot capabilities (custom-nethack-engine change) are consumed here but not modified. -->

## Impact

- **Code**: `tools/play_server.py` (restructured into a multi-page app; HTML/CSS/JS split for readability), possibly new `tools/webconsole/` templates/static assets. Consumes `nethack_core.engine_env.EngineEnv` and the difficulty-tuning surface unchanged.
- **Engine**: the vision-reduce fix may need a small engine/binding affordance (a forced full re-render / display recompute) since reducing `reveal_map` must re-blank now-out-of-vision cells; the mechanism is settled in design.
- **Dependencies**: none new (Flask + PIL already present).
- **Legacy**: the Textual launchpad (`tools/launchpad`) is superseded as the primary interface; not removed in this change.
```

## openspec/changes/web-console/design.md

- Source: openspec/changes/web-console/design.md
- Lines: 1-45
- SHA256: f85d2ee7139fad47f79c414c54b3795b4e14feac09a8e91f86b3c23731e55c34

```md
# Design — web-console

High-level architecture decisions. Details (exact endpoints already exist; this is about structure + the two genuinely new pieces: the multi-page shell and the vision-reduce fix) are settled in the design phase / brainstorming.

## Architecture

A single Flask app (evolved from `tools/play_server.py`) serving **multiple HTML pages** that share one stylesheet and a small JS module, all backed by the existing JSON API over one `EngineEnv`.

```
GET /          -> landing  (description + GIFs + nav; no game)
GET /map       -> Map Viewer page
GET /obs       -> Observation Creator page
GET /traces    -> Tracer page
JSON API (unchanged): /reset /step /live /set_tune /catalog
                      /record_start /record_stop /traces /trace /gif/<n> /gifs
```

**Page delivery choice (decide in design):** server-rendered separate HTML routes (clean URLs, each page is its own template) vs a single-page app with client routing. Lean toward **separate server-rendered pages** with a shared `static/console.css` + `static/console.js`, because it splits the "cooked" blob into readable per-page templates and gives real navigable URLs.

**Shared assets:** the map colorizer, the knob-control builder, and the API helpers move into `static/console.js`; the retro theme (gray tiles, pastel accents) into `static/console.css`. Each page template includes them and wires only its own widgets.

## The retro theme

Gray dungeon-tile background with pastel highlight accents (hero/stairs/items), monospace, NetHack-ish. The landing page reads like a README: title, one-paragraph description of the engine + knobs + snapshot/replay, the knob-effect GIF gallery, and three large nav cards (Map Viewer / Observation Creator / Tracer).

## Page responsibilities

- **Map Viewer** — the current Play tab: live map render (structured chars+colors+message+status), keyboard commands, the grouped knob sidebar (Vision / Stat-based / Dungeon & spawns; bool switches; slider + editable number), Reset/regenerate, Record toggle. Live knobs apply immediately; reset knobs stage for Reset.
- **Observation Creator** — configure a reproducible observation/scenario: seed + generation knobs + reveal, regenerate, step to a target state, and **export** it (snapshot handle and/or the raw observation as JSON) for reuse as an eval/training starting point. (Exact export format + whether it persists a snapshot is a design decision; v1 may export the obs JSON + the seed/tune config.)
- **Tracer** — the current Traces tab: list `.ndjson` rollouts, scrub turns, render map + status + reward + messages + LLM panes.

## Vision-reduce re-render (the fix)

Today live vision changes refresh via a ctrl-R redraw step, which re-runs `vision_recalc` and *adds* revealed cells — fine for increasing visibility. Reducing visibility (reveal off, smaller radius, fog on) does not visibly update because (a) the client only re-renders on the returned obs and (b) NetHack keeps already-seen terrain in hero memory (`gbuf`), so a plain redraw won't re-blank cells the reveal had shown.

Options (settle in design):
1. **Client + redraw is enough for radius/fog:** confirm whether a ctrl-R redraw already re-blanks for `vision_radius`↓ / `fog_of_war` on (it recomputes could-see); if so, the fix is just to always re-render after any live vision change (including reductions) — a client/server-glue fix, no engine change.
2. **reveal_map↓ needs memory clear:** because reveal wrote remembered terrain into `gbuf`, turning it off cannot un-remember without clearing hero memory of out-of-sight cells. If that behavior is wanted, add a small engine/binding affordance (a "redraw from current vision only" / clear-unseen helper) and call it on a vision-reduce.

The fix must at minimum guarantee the **observation re-renders immediately** on any vision-knob change in either direction; whether reveal-off fully un-reveals previously-seen terrain is the open design question.

## Non-goals
- No protocol/JSON-API redesign.
- No removal of the Textual launchpad.
- No new engine knobs (consumes the existing catalog).
```

## openspec/changes/web-console/tasks.md

- Source: openspec/changes/web-console/tasks.md
- Lines: 1-31
- SHA256: 25c36f1e47e5ca5cd9f5be456e0539a7942fb648dd4b5924fd56339a1dfbccde

```md
# Tasks — web-console

## 1. Structure + theme
- [ ] 1.1 Split `play_server.py` into a multi-page Flask app: shared `static/console.css` (retro gray tiles + pastel accents) and `static/console.js` (colorizer, knob builder, API helpers); per-page templates.
- [ ] 1.2 Keep the JSON API endpoints unchanged (`/reset`, `/step`, `/live`, `/set_tune`, `/catalog`, `/record_*`, `/traces`, `/trace`, `/gif*`).

## 2. Landing page (`/`)
- [ ] 2.1 README/description of the console + engine capabilities (knobs, snapshot/replay, generation).
- [ ] 2.2 Embedded knob-effect GIF gallery (served from `/gif/<name>`).
- [ ] 2.3 Three nav cards linking to Map Viewer / Observation Creator / Tracer. No game controls on the landing page.

## 3. Map Viewer (`/map`)
- [ ] 3.1 Live map render (structured chars+colors+message+status) + keyboard commands.
- [ ] 3.2 Grouped knob sidebar (Vision / Stat-based / Dungeon & spawns); bool switches; slider + editable number; live vs reset apply; Reset/regenerate; Record toggle.

## 4. Observation Creator (`/obs`) — metric composition + plotting
- [ ] 4.1 Load rollouts (reuse the `.ndjson` list); adapter from our TraceTurn fields to the `records` shape `tools/rollout_view.stats` expects.
- [ ] 4.2 `GET /obs/metrics` (built-in series) + `POST /obs/plot` (paths + metrics + a custom composition over existing series via `register_custom_metric`; restricted operator set, no arbitrary eval).
- [ ] 4.3 Render plots via `tools/rollout_view` `_svg_linechart` / `render_dashboard`; embed in the page.

## 5. Tracer (`/traces`)
- [ ] 5.1 List `.ndjson` rollouts; scrubber over turns; render map + status + reward + messages + LLM panes.

## 6. Vision-reduce fix — reveal/fog as obs overlays (fork C)
- [ ] 6.1 Remove the `gbuf`-mutating reveal from `vision_recalc`; implement `reveal_map`/`fog_of_war` as a render-time overlay in `win/rl/winrl.cc fill_obs` (fill unknown cells from `level->locations`, never touch `gbuf`).
- [ ] 6.2 `/live` re-renders on any vision change (both directions); `vision_radius` unchanged.
- [ ] 6.3 Tests: `reveal_map` 1→0 drops obs cell count back; `gbuf`/normal-play obs unaffected (golden parity holds); rebuild the engine.

## 7. Verify
- [ ] 7.1 Smoke each page (landing/map/obs/traces serve + their core API calls).
- [ ] 7.2 Confirm the Textual launchpad still imports (legacy, untouched) and existing engine tests still pass.
```

## openspec/changes/web-console/specs/web-console/spec.md

- Source: openspec/changes/web-console/specs/web-console/spec.md
- Lines: 1-40
- SHA256: f56fc9f4db553f3ebf767fe156422a80c09c84074ff413316deedeab73cb928f

```md
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
```

