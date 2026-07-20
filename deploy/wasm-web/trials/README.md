# Replay data for the Replays page

Static JSON, generated — **do not hand-edit**. `replays.js` reads:

| file | contents |
|---|---|
| `index.json` | one row per trial: `{id, agent, seed, outcome, max_dlvl, turns, kind, variant, backend}` — drives the list, the filters and the summary chart |
| `<id>.json` | `{meta, turns[]}` for one trial, fetched only when that trial is clicked |
| `CURATED.txt` | which trials ship (input to the exporter, not read by the page) |

A turn is one of two `kind`s, because the two agent architectures record
different things: `grid` (code-mode / `rlm`) carries a map plus the code the
agent generated, `skill` (`voyager`) carries one skill-library iteration —
objective, composed macro, per-primitive feedback — and **no map**.

## Swapping trials in and out

1. Edit `CURATED.txt` (one run-dir name per line; `#` comments and blank lines
   are ignored). Names must match the source directories exactly — the exporter
   fails loudly on a name it can't find rather than silently shipping less.
2. Re-export:

   ```sh
   python tools/export_trials.py \
     --root <dir-of-run-dirs> \
     --only @deploy/wasm-web/trials/CURATED.txt
   ```

   Drop `--only` to ship the entire corpus (~9 MB for 40 trials, vs ~2 MB for
   the curated set). Each trial is ~17 KB gzipped over the wire and loaded on
   demand, so page weight scales with what a visitor *clicks*, not with the
   corpus size — the repo cost is the reason to curate, not the load time.
3. Nothing else to rebuild: this is data, not part of the WASM engine.

The source traces are run directories named `<agent>_seed<N>_<OK|FAIL>_dlvl<D>`,
each containing one or more `.ndjson` files. The label in the directory name is
cross-checked against the trace, so a mislabelled directory aborts the export.

## Known issue — recorded trials are a different character than live play

**"Play this seed" does not currently reproduce the trial's game.** The browser
console hard-codes a **Valkyrie** (`name:Agent-Val-hum-neu-fem`, in
`web/console_backend.js`), while the harness that recorded these traces defaults
to a **Monk** (`_DEFAULT_CHARACTER = "mon-hum-neu-mal"`, `nethack_core/_engine.py`).
Role feeds level generation, so the same seed yields a different dungeon as well
as a different hero.

Until that is reconciled, the hand-off link is "play this seed", not "replay
this game". Two ways to fix it, whenever it gets picked up:

- make the console's character configurable and set it per trial from the
  trial's own metadata (needs the character recorded into the trace — it is
  **not** in the current `meta`, which only has `variant` and `backend`); or
- re-record the corpus with the Valkyrie the console uses.

The second is cleaner but throws away the existing traces. Whichever way it
goes, `meta` should start carrying the character so this can never drift
silently again.
