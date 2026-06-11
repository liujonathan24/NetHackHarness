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

## 4. Observation Creator (`/obs`)
- [ ] 4.1 Configure a scenario: seed + generation knobs + reveal; regenerate; step to a target state.
- [ ] 4.2 Export the observation/scenario (obs JSON and/or snapshot handle + seed/tune config) for reuse.

## 5. Tracer (`/traces`)
- [ ] 5.1 List `.ndjson` rollouts; scrubber over turns; render map + status + reward + messages + LLM panes.

## 6. Vision-reduce re-render fix
- [ ] 6.1 Reducing any vision knob (`vision_radius`↓, `fog_of_war` on, `reveal_map` off) forces an immediate re-render reflecting the reduced setting.
- [ ] 6.2 Determine + implement the mechanism (client always-re-render vs an engine "redraw from current vision" affordance for reveal-off); add a test that a vision reduction changes the rendered cell count.

## 7. Verify
- [ ] 7.1 Smoke each page (landing/map/obs/traces serve + their core API calls).
- [ ] 7.2 Confirm the Textual launchpad still imports (legacy, untouched) and existing engine tests still pass.
