# Tasks — web-console

## 1. Structure + theme
- [x] 1.1 Split `play_server.py` into a multi-page Flask app: shared `static/console.css` (retro gray tiles + pastel accents) and `static/console.js` (colorizer, knob builder, API helpers); per-page templates.
- [x] 1.2 Keep the JSON API endpoints unchanged (`/reset`, `/step`, `/live`, `/set_tune`, `/catalog`, `/record_*`, `/traces`, `/trace`, `/gif*`).

## 2. Landing page (`/`)
- [x] 2.1 README/description of the console + engine capabilities (knobs, snapshot/replay, generation).
- [x] 2.2 Embedded knob-effect GIF gallery (served from `/gif/<name>`).
- [x] 2.3 Three nav cards linking to Map Viewer / Observation Creator / Tracer. No game controls on the landing page.

## 3. Map Viewer (`/map`)
- [x] 3.1 Live map render (structured chars+colors+message+status) + keyboard commands.
- [x] 3.2 Grouped knob sidebar (Vision / Stat-based / Dungeon & spawns); bool switches; slider + editable number; live vs reset apply; Reset/regenerate; Record toggle.

## 4. Observation Creator (`/obs`) — metric composition + plotting
- [ ] 4.1 Load rollouts (reuse the `.ndjson` list); adapter from our TraceTurn fields to the `records` shape `tools/rollout_view.stats` expects.
- [ ] 4.2 `GET /obs/metrics` (built-in series) + `POST /obs/plot` (paths + metrics + a custom composition over existing series via `register_custom_metric`; restricted operator set, no arbitrary eval).
- [ ] 4.3 Render plots via `tools/rollout_view` `_svg_linechart` / `render_dashboard`; embed in the page.

## 5. Tracer (`/traces`)
- [x] 5.1 List `.ndjson` rollouts; scrubber over turns; render map + status + reward + messages + LLM panes.

## 6. Vision-reduce fix — reveal/fog as obs overlays (fork C)
- [x] 6.1 Remove the `gbuf`-mutating reveal from `vision_recalc`; implement `reveal_map`/`fog_of_war` as a render-time overlay in `win/rl/winrl.cc fill_obs` (fill unknown cells from `level->locations`, never touch `gbuf`).
- [x] 6.2 `/live` re-renders on any vision change (both directions); `vision_radius` unchanged.
- [x] 6.3 Tests: `reveal_map` 1→0 drops obs cell count back; `gbuf`/normal-play obs unaffected (golden parity holds); rebuild the engine.

## 7. Verify
- [x] 7.1 Smoke each page (landing/map/obs/traces serve + their core API calls).
- [x] 7.2 Confirm the Textual launchpad still imports (legacy, untouched) and existing engine tests still pass.
