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
