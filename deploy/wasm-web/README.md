# NetHack in the browser (WebAssembly)

This directory is a **self-contained static site** that runs the NetHack web
console (the local Flask app's Map Viewer) entirely **client-side in the visitor's
browser** — no server, no hosted runtime. It's the same UI (`console.js`/`console.css`,
unchanged) driven by a `fetch()` shim (`console_backend.js`) over the WASM engine.

## What's here

| File | Purpose |
|------|---------|
| `index.html` | the Map Viewer page (screen, grouped difficulty knobs, modify panel, undo/checkpoint, six-level curriculum toggle) |
| `console.js` / `console.css` | the local web console's client + styles, used **unchanged** |
| `console_backend.js` | client-side backend: a `fetch()` shim implementing the console's JSON API (`/catalog` `/reset` `/step` `/live` `/undo` `/mark` `/modify`) over the engine |
| `nethack.js` | Emscripten JS loader/glue |
| `nethack.wasm` | the NLE engine compiled to WebAssembly (~3.7 MB) |
| `nethack.data` | preloaded NetHack data files |

Total ~5 MB, downloaded once and cached by the browser.

## How it works

The engine's stackful coroutine (deboost/fcontext) has no WebAssembly backend, so
it's re-implemented on Emscripten's fiber API over **Asyncify** — no threads,
no `SharedArrayBuffer`, so it hosts on **any plain static file host** (GitHub Pages,
Hugging Face Static Space, Netlify, S3, …) with **no COOP/COEP headers**.

The curriculum "Start here" button places the hero directly on any of the 6
curriculum floors (Dungeons of Doom 1-3 / Gehennom 48-50) via a cross-branch
`nle_goto_abs` jump — the reverse-curriculum research setup, running locally.

Also in the page:
- **Difficulty knobs** — HP scale, damage-to-you, monster difficulty, reveal-map
  (17-knob catalog under the hood), applied at game start.
- **Undo / Save state / Load state** — deterministic replay of the seed + action
  log. "Save state" copies a ~100-byte shareable string; "Load state" rebuilds the
  exact game (position, HP, everything) anywhere.

## Run locally

```sh
# any static file server works; python's is enough
cd deploy/wasm-web
python3 -m http.server 8099
# open http://localhost:8099
```

`file://` will **not** work (browsers block `fetch` of the `.wasm`/`.data` over
`file://`) — you need an `http(s)://` origin, which is exactly what a static host gives you.

## Host it free on GitHub Pages

A workflow at `.github/workflows/deploy-wasm-pages.yml` publishes this directory to
GitHub Pages automatically. To enable it: repo **Settings → Pages → Source: GitHub
Actions**. After the next push the site is live at
`https://<user>.github.io/<repo>/`.

## Rebuild the bundle

The artifacts are produced from the NetHack fork (`third_party/NetHack`) — see
`src/build_wasm_dat.sh` (regenerates the wasm-ABI data) and `src/build_wasm.sh`
(compiles the engine). The optimized release link and this bundle are produced by
`deploy/wasm-web/rebuild.sh`.
