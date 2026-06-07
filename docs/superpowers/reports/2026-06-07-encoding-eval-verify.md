# Verification Report: encoding-eval (roadmap M3)

Date: 2026-06-07 · Mode: full · Branch: encoding-eval

## Summary

| Dimension | Status |
|---|---|
| Completeness | 14/14 tasks checked; 1/1 capability implemented |
| Correctness | 12/12 spec scenarios covered by tests |
| Coherence | Matches Design Doc + delta spec (runner-reuse, pure aggregation, trace-extension capture, minimal renderer + Group B seam); no drift |

## Completeness

- `tasks.md`: 14/14 `[x]`.
- Capability `encoding-eval`: aggregation (`tools/encoding_eval/aggregate.py`),
  orchestration (`run.py`), replay capture (`nethack_harness/helpers.py` +
  `nethack.py`), minimal renderer + seam (`replay.py`), VLM config
  (`configs/eval/qwen-3-5-vl.toml`), run README.

## Correctness — scenario → test (12/12)

| Scenario | Test |
|---|---|
| Runs the encoding matrix | `test_dispatches_each_cell_with_variant_and_detail` |
| Encoding set is configurable data | same (matrix is a dict arg; cell keys) |
| Aggregation uses existing summarizer | `test_table_has_one_row_per_encoding` (ci_lo/hi, progression_tier) |
| Token cost reported per encoding | `test_table_has_one_row_per_encoding` (tokens_per_turn) |
| Missing usage marked, not guessed | `test_missing_usage_marks_cost_unavailable` |
| Aggregation runs on mock samples | `test_table_has_one_row_per_encoding` (pure) |
| Comparison table emitted | `test_table_to_markdown_renders_rows_and_na` |
| Human-viewable timeline | `test_human_form_shows_game_state` |
| LLM-input form for text encoding | `test_llm_form_shows_text_and_image_ref` |
| LLM-input form preserves image (pixel) | `test_llm_form_shows_text_and_image_ref` + `test_image_content_written_as_png_and_referenced` |
| Full multimodal content captured | `test_image_content_written_as_png_and_referenced` |
| Viewer is a marked integration seam | `test_seam_documents_log_keys` |

## Test evidence

- New tests in isolation: 9 passed (aggregation 3, replay capture 2, renderer 3, orchestration 1).
- Full suite: **374 passed / 7 failed** — the 7 are EXACTLY the pre-existing baseline (`test_integration::test_success_reward_zero_then_one` + 6 × `test_rewards`, ordering pollution). Zero new failures.

## Security

No hardcoded secrets. No new `exec`/`unsafe`. `_capture_user_content` decodes
base64 image data already produced by the harness and writes PNGs under the
configured trace dir — no untrusted input path.

## Coherence / scope

- Design decisions implemented as specified: runner-reuse orchestration (injectable
  seam), pure aggregation (mock-testable), NDJSON trace extension + separate-PNG
  image capture, Qwen instruct+VL default config, minimal renderer behind the
  documented `REPLAY_LOG_KEYS` seam.
- Out of scope, as designed: running the paid real benchmark (operational follow-up,
  documented in `tools/encoding_eval/README.md`); the rich Group B viewer.

## Notable finding (fixed in this change)

The per-turn trace writer (`_write_trace_entry`) referenced `Path` without importing
it, so it raised `NameError` inside its `try/except` on every call — **all trace
writing was silently disabled repo-wide**. Fixed by adding `from pathlib import
Path`. This is load-bearing: the replay capture (and any prior `trace_dir` use)
depends on it. Verified safe — every name in the function now resolves.

## Issues

- CRITICAL: none. WARNING: none.
- SUGGESTION (non-blocking): `_capture_user_content` assumes list entries are dicts
  (a malformed entry would drop that turn's trace line via the swallowing
  try/except); image extension hardcoded `.png` (fine for IMG/IMG_TTY which emit
  PNG). Both noted in the Task-2 review.

## Assessment

No critical/warning issues. All 12 scenarios covered, full suite green modulo the
documented baseline, plus a load-bearing latent-bug fix. **Ready for archive.**
