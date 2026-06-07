## 1. Aggregation layer (pure, mock-testable)

- [x] 1.1 Add an aggregation module (`tools/encoding_eval/aggregate.py`) that takes `{cell_key: list[sample_dict]}` and returns a per-encoding metrics table, reusing `tools/eval_instrument.summarize_eval` + `nethack_harness/prompt/balrog.progression_score/tier`.
- [x] 1.2 Compute per cell: progression score/tier, max dlvl, descent rate + Wilson CI, scout/avg_score, tokens/turn; mark $/run unavailable (`None`/"n/a") when usage is absent.
- [x] 1.3 Emit the comparison table (structured dict + `table_to_markdown`) — the orchestrator/run-note writes `table.json` + `table.md` under `outputs/evals/`.
- [x] 1.4 Unit-test aggregation on synthetic sample dicts (no model calls); asserts table shape + summarize_eval/progression used + missing-usage marked.

## 2. Matrix orchestration

- [x] 2.1 Add `tools/encoding_eval/run.py` `run_matrix(matrix, *, runner)` running each `(encoding, model)` cell via an injectable runner seam (default raises NotImplementedError so CI injects a stub); aggregates via `aggregate_cells`.
- [x] 2.2 Encoding set + models are configuration-driven (data, not code); cell keys distinguish `map_detail` (e.g. `JSON:minimal`).
- [x] 2.3 Test orchestration with a stub runner (no real model calls) — asserts each cell dispatched with the right variant/map_detail.

## 3. Replayable rollout logs — CAPTURE (in scope; viewer deferrable to Group B)

- [x] 3.1 Capture full multimodal content per turn: `_capture_user_content` + `rendered_user_content` in `_write_trace_entry`; IMG/IMG_TTY images written as PNGs under `<run>/images/`, referenced by path (no inline base64). (Also fixed a latent `Path`-unimported bug that had silently disabled the whole trace writer.)
- [x] 3.2 Human-viewable timeline: the per-turn `raw_grid` (tty frames) is captured in the trace; `render_replay(form="human")` renders it (reuses the existing tty capture; `legacy/replay.py` recorder available for richer frames).
- [x] 3.3 Documented on-disk replay-log format + marked entry point: `tools/encoding_eval/replay.py` `render_replay(run_dir, form=human|llm)` + `REPLAY_LOG_KEYS` (the seam Group B's `tools/launchpad` viewer reads). Minimal renderer ships; rich viewer is a Group B integration.
- [x] 3.4 Tests: multimodal turn captures the image (not elided); minimal renderer reproduces text-form and image-form per turn from a fixture; seam keys present.

## 4. VLM config

- [x] 4.1 Add `configs/eval/qwen-3-5-vl.toml` (Qwen3.5-VL) mirroring the existing TOML shape so IMG/IMG_TTY are exercisable.

## 5. Verification

- [x] 5.1 New tests pass in isolation (8); full suite 374 passed / 7 failed (== pre-existing baseline; zero new failures).
- [x] 5.2 Operational run documented in `tools/encoding_eval/README.md` (supply a real runner + model configs incl. the VLM; set trace_dir; render replay; read table.json/md).
