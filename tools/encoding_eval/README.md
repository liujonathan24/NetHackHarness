# encoding-eval

Benchmark the NetHack observation encodings (ASCII / IMG / IMG_TTY / JSON / TOON,
with `map_detail`) across models, reusing the existing eval instrumentation.

## Layers

- `aggregate.py` — **pure**: `aggregate_cells({cell: [sample, ...]}) -> {"rows": {...}}`
  (reuses `tools.eval_instrument.summarize_eval` + `nethack_harness.prompt.balrog`
  progression). `table_to_markdown(table)` renders it. No model calls.
- `run.py` — `run_matrix(matrix, *, runner)` orchestrates the `(encoding, model)`
  matrix through an **injectable runner** seam and aggregates. Tests inject a stub.
- `replay.py` — `render_replay(run_dir, *, form="human"|"llm")` renders a recorded
  rollout in either the human-viewable game-state form (tty `raw_grid` frames) or
  the exact LLM-input form (text + image path refs). `REPLAY_LOG_KEYS` is the
  stable on-disk seam the Group B `tools/launchpad` viewer reads.

## Replay capture

Per-turn traces (written by `nethack_harness/helpers.py` `_write_trace_entry` when
`trace_dir` is set) now include `rendered_user_content` — the full multimodal
content. For IMG / IMG_TTY the image is written to `<run_dir>/images/` and
referenced by path (not inline base64), so the exact pixels the VLM saw are
replayable.

## Running a real benchmark (operational follow-up)

The harness code is testable with mock samples; a *real* run needs model API
access + budget:

1. Supply a real `runner(cell)` to `run_matrix` that renders a per-cell
   `configs/eval`-style config (env `nethack` + the cell's `variant`/`map_detail`
   + model — see `configs/eval/qwen-3-5.toml` for the instruct LLM and
   `configs/eval/qwen-3-5-vl.toml` for the VLM), invokes the existing
   vf-eval/prime runner, sets `trace_dir` to `outputs/evals/<run>/`, and returns
   samples via `tools.eval_instrument.load_hosted_eval_samples` /
   `attach_local_traces`.
2. Write the aggregated table to `outputs/evals/<run>/table.json` and
   `table.md` (via `table_to_markdown`).
3. Inspect rollouts with `render_replay(run_dir, form="human")` and
   `render_replay(run_dir, form="llm")`.
