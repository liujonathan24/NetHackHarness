---
change: web-console
design-doc: docs/superpowers/specs/2026-06-11-web-console-design.md
base-ref: a59cd468a7037a269fe22131f24d793b1a9c0ace
archived-with: 2026-06-11-web-console
---

# Plan — web-console

Build the multi-page retro web console (landing + Map Viewer + Observation Creator + Tracer), reimplement reveal/fog as reversible obs overlays, all on `EngineEnv`. See the Design Doc for rationale; this is the execution order. Commit per task; check off tasks.md.

## Task 1 — Engine: reveal/fog as obs overlays (fork C)
Move `reveal_map`/`fog_of_war` out of `nle_reveal_level()`/`gbuf` into the rl-port obs fill so reducing them hides instantly with no game-state/perf impact.
- In `win/rl/winrl.cc fill_obs`, after the normal map arrays are populated, if `reveal_map>0 || fog_of_war==0`, fill every still-unknown cell from `level->locations` (terrain → glyph/char/color, same mapping the magic-map path uses) directly into `glyphs_/chars_/colors_` — never touching `gbuf`.
- Remove the `gbuf`-mutating reveal call from `vision_recalc` (vision.c). Keep `vision_radius` (nv_range) untouched.
- Rebuild the engine.
- **Test** (`environments/nethack/tests/test_vision_overlay.py`): `reveal_map` 1→0 drops obs cell count back to the pre-reveal value; a normal step after reveal-off behaves as if reveal never ran (no remembered residue); golden parity still holds.
- Commit (fork + bump submodule pointer; harness test).

## Task 2 — Web shell + retro theme
Split `tools/play_server.py` into a multi-page Flask app.
- `tools/webconsole/templates/{base,landing,map,obs,traces}.html`, `tools/webconsole/static/{console.css,console.js}`.
- `console.css`: dark gray dungeon tiles, pastel accents, monospace. `console.js`: `colorize`, knob-control builder, API helpers, keymap (extracted from the current inline JS).
- Routes: `GET /` landing, `/map`, `/obs`, `/traces` via `render_template`; JSON API endpoints unchanged.
- Commit.

## Task 3 — Landing page (`/`)
Description/README of the console + engine capabilities; embedded GIF gallery (`/gif/<name>`); three nav cards to the pages. No game controls. Commit.

## Task 4 — Map Viewer (`/map`)
Port the current Play tab: live map render + keyboard, grouped knob sidebar (switches/sliders+number/editable), Reset, Record toggle, live-vs-reset apply. `/live` re-renders on any vision change (now reversible via Task 1). Commit.

## Task 5 — Tracer (`/traces`)
Port the current Traces tab: list `.ndjson`, scrubber, per-turn render (map+status+reward+messages+LLM panes). Commit.

## Task 6 — Observation Creator (`/obs`)
Wire `tools/rollout_view` into the web.
- Adapter: load `.ndjson` rollouts into the `records` shape `rollout_view.stats` expects (map our TraceTurn fields).
- `GET /obs/metrics` (built-in series names); `POST /obs/plot` (paths + metrics + a custom composition over existing series via `register_custom_metric`; restricted operator set — no arbitrary eval).
- Render via `_svg_linechart`/`render_dashboard`; embed the SVG in the page.
- Commit.

## Task 7 — Verify
- Per-page serve smokes (`/`, `/map`, `/obs`, `/traces`) + core API calls.
- Vision-overlay test passes; existing engine test suite green; Textual launchpad still imports (legacy untouched).
- Commit.
