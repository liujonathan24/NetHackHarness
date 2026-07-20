# NetHack Console in the browser (WebAssembly)

This directory is a **self-contained static site** — three pages, no server, no
hosted runtime. The engine is compiled to WebAssembly and the recorded agent
trials are shipped as flat JSON, so the whole thing hosts on any plain static
file host.

| Page | What it is | Downloads the engine? |
|---|---|---|
| `index.html` | **Intro** — what the project is and how it differs from vanilla NetHack | no |
| `replays.html` | **Replays** — 40 recorded LLM-agent trials, scrubbable turn by turn | no |
| `play.html` | **Map Viewer** — the local Flask console's live play page, client-side | yes (~5 MB) |

Live play sits behind its own page so the landing and replay surfaces load
instantly; only a visitor who chooses to play pays for the engine.

## What's here

| File | Purpose |
|------|---------|
| `console.js` / `console.css` | the local web console's client + styles, **byte-identical** to `tools/webconsole/static/` |
| `console.extra.css` | the only new styling (Intro + Replays selectors), kept separate so the two files above stay identical |
| `console_backend.js` | client-side backend: a `fetch()` shim implementing the console's JSON API (`/catalog` `/reset` `/step` `/live` `/undo` `/mark` `/modify`) over the engine |
| `replays.js` | drives the Replays page off `trials/*.json` (reuses `colorize()`/`escHtml()` from `console.js`) |
| `trials/` | `index.json` + one JSON per recorded trial, written by `tools/export_trials.py` |
| `nethack.js` | Emscripten JS loader/glue |
| `nethack.wasm` | the NLE engine compiled to WebAssembly (~3.7 MB) |
| `nethack.data` | preloaded NetHack data files |

## How it works

The engine's stackful coroutine (deboost/fcontext) has no WebAssembly backend, so
it's re-implemented on Emscripten's fiber API over **Asyncify** — no threads,
no `SharedArrayBuffer`, so it hosts on **any plain static file host** (GitHub Pages,
Hugging Face Static Space, Netlify, S3, …) with **no COOP/COEP headers**.

The Map Viewer is the real console UI. `console_backend.js` answers the exact JSON
endpoints `console.js` already spoke to, so the client is used unmodified:

- **Difficulty knobs** — the same 17-knob catalog in the same three groups as
  `tools/play_server.py`, applied live or at reset.
- **Undo / Checkpoint / Restore** — deterministic replay of `{seed, tune,
  curriculum, action journal}`, so no C-level snapshot is needed in the browser.
- **Six-level curriculum** — start on Dungeons of Doom 1–3 or Gehennom 48–50 via a
  cross-branch `nle_goto_abs` jump.

The Replays page is the local console's Tracer with static JSON in place of
`/traces` + `/trace?path=`. Two agent architectures are in the corpus and record
different things, so a turn renders one of two ways: a **map + the code the agent
generated** (code-mode runs) or a **skill-library iteration** — objective, composed
macro, per-primitive feedback (Voyager-style runs). Each trial's header links to
`play.html?seed=…&dlvl=…`, handing the live engine the seed and floor being viewed.

## Run locally

```sh
# any static file server works; python's is enough
cd deploy/wasm-web
python3 -m http.server 8099
# open http://localhost:8099
```

`file://` will **not** work (browsers block `fetch` of the `.wasm`/`.data`/`.json`
over `file://`) — you need an `http(s)://` origin, which is exactly what a static
host gives you.

## Host it free on GitHub Pages

`.github/workflows/deploy-wasm-pages.yml` publishes this directory on every push to
`main` (it self-enables Pages via `configure-pages` `enablement: true`). The site is
live at `https://<user>.github.io/<repo>/`.

## Rebuild the bundle

Engine artifacts come from the NetHack fork (`third_party/NetHack`) — see
`src/build_wasm_dat.sh` (regenerates the wasm-ABI data) and `src/build_wasm.sh`
(compiles the engine). The optimized release link, the page/asset copies, and the
trial export are all driven by `deploy/wasm-web/rebuild.sh`:

```sh
TRIALS_ROOT=/path/to/runs ./deploy/wasm-web/rebuild.sh   # re-export trials too
./deploy/wasm-web/rebuild.sh                             # keep the committed trials
```

To refresh only the replay data:

```sh
python3 tools/export_trials.py --root /path/to/runs --out deploy/wasm-web/trials
```
