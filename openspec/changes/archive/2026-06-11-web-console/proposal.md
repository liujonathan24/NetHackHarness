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
