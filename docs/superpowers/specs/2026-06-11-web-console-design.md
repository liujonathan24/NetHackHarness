---
comet_change: web-console
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-11-web-console
status: final
---

# Web Console — Technical Design

Deep design for the `web-console` change. OpenSpec proposal/spec are the source of truth for WHAT; this covers HOW.

## 1. Shell: multi-page Flask app

Evolve `tools/play_server.py` from one HTML blob into a small multi-page app:

```
tools/play_server.py            # routes + JSON API (unchanged endpoints)
tools/webconsole/
  templates/  base.html  landing.html  map.html  obs.html  traces.html
  static/     console.css   console.js
```

- `base.html`: shared `<head>` (retro theme), a top nav, includes `console.css` + `console.js`.
- Each page template extends `base.html` and includes only its widgets.
- `console.js` exports the shared bits used by >1 page: `colorize(rows,colors)`, the knob-control builder, the `post()`/`fetch` API helpers, the keyboard map.
- Flask routes: `GET /` (landing), `/map`, `/obs`, `/traces`. JSON API stays exactly as today (`/reset /step /live /set_tune /catalog /record_* /traces /trace /gif*`) — this is a presentation refactor, not a protocol change. Use `render_template` (Flask/Jinja already available via Flask).

**Theme** (`console.css`): dark gray dungeon-tile background, pastel accent palette for hero/stairs/items/monsters, monospace. Landing reads like a README: title, one-paragraph description (engine + knobs + snapshot/replay), the GIF gallery (`/gif/<name>`), and three large nav cards.

## 2. Map Viewer (`/map`)

Lift the current Play tab verbatim into `map.html` + the shared JS: structured map render, keyboard commands, grouped knob sidebar (Vision / Stat-based / Dungeon & spawns; bool switches; slider + editable number), Reset/regenerate, Record toggle, live-vs-reset apply.

## 3. Tracer (`/traces`)

Lift the current Traces tab: `/traces` list, scrubber, per-turn render (map + status + reward + messages + LLM panes), backed by the existing `/traces` + `/trace` endpoints.

## 4. Observation Creator (`/obs`) — metric composition + plotting

Revives the rollout observation viewer using the existing `tools/rollout_view`:
- `tools/rollout_view/stats.py`: `series(records, name)`, `register_metric(...)`, `run_summary`, `aggregate`.
- `tools/rollout_view/dashboard.py`: `_svg_linechart(...)`, `render_dashboard(runs, ...)`.

Page flow:
1. Pick one or more rollouts (the same `.ndjson` list as the Tracer, parsed to the `records` shape `rollout_view` expects).
2. Choose built-in series and/or define a **custom metric as a composition of existing ones** (e.g. `explevel + k * dungeon_depth`). Wire this through `register_metric` (via a safe AST evaluator, no arbitrary eval) so it is applied post-hoc to the loaded records.
3. Plot via `_svg_linechart` / `render_dashboard` (server renders the SVG; the page embeds it).

New endpoints (thin wrappers over `rollout_view`):
- `GET /obs/metrics` → available built-in metric names.
- `POST /obs/plot` → body `{paths:[...], metrics:[...], custom:{name, expr}}` → returns SVG (or series JSON the page charts). The custom `expr` is a restricted composition over existing series (safe-eval / a tiny operator set — NOT arbitrary `eval`).

**Risk:** the `records` shape `rollout_view.stats.series` expects must match our `.ndjson` turns. Adapt at load time (map our TraceTurn fields → the metric extractor's expected keys). Confirm against `tools/rollout_view/stats.py` field access; add an adapter if needed.

## 5. Vision-reduce: reveal/fog as obs overlays (fork C change)

Today `reveal_map`/`fog_of_war=0` call `nle_reveal_level()` which `magic_map_background()`s into `gbuf` (the hero's remembered map) inside `vision_recalc`. That permanently remembers the terrain, so reducing the knob can't un-hide it (verified: 614 cells stay).

Change: make reveal a **render-time overlay on the observation buffers**, never touching `gbuf`:
- Remove the `gbuf`-mutating reveal from `vision_recalc`.
- In the rl-port obs fill (`win/rl/winrl.cc fill_obs`, after the normal `glyphs_/chars_/colors_` are populated from `gbuf`): if `reveal_map` (or `fog_of_war==0`), for every cell not already known, write the level's background glyph/char/color directly into the obs arrays (`level->locations` terrain → glyph via the same mapping `magic_map_background` would use). This affects only the emitted observation, not `gbuf`.
- Result: reveal on → obs shows the floor; reveal off → obs shows only genuinely seen/remembered cells, immediately, with no state change. The overlay path runs only when the knob is non-default, so the base game is byte-identical and unaffected in speed (golden parity preserved).

`vision_radius` is unchanged (genuine night-vision range; remembered cells correctly persist when reduced). The web `/live` path still drives the refresh (the redraw/obs-refresh already re-emits the obs each change).

**Testing:** binding-level test that `reveal_map` 1→0 drops the obs cell count back to the pre-reveal value AND that `gbuf`/subsequent normal-play obs is unaffected (parity); per-page serve smokes; existing engine tests stay green.

## 6. Build order

All-at-once (user choice), but internally: (1) shell + theme + Map + Tracer (pure refactor of working code), (2) vision overlay fork change + test, (3) Observation Creator over `rollout_view`. Commit per piece. Keep the Textual launchpad untouched (legacy).

## Non-goals
- No JSON-protocol redesign, no launchpad removal, no new difficulty knobs, no snapshot→bytes serialization.
