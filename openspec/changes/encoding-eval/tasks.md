## 1. Aggregation layer (pure, mock-testable)

- [ ] 1.1 Add an aggregation module that takes `{cell_key: list[sample_dict]}` and returns a per-encoding metrics table, reusing `tools/eval_instrument.summarize_eval` + `nethack_harness/prompt/balrog.progression_score/tier`.
- [ ] 1.2 Compute the required metrics per cell: progression score/tier, max dlvl, descent rate + Wilson CI, scout coverage, steps-to-first-descent, tokens/turn; mark $/run unavailable when usage is absent.
- [ ] 1.3 Emit the comparison table (structured + human-readable) under `outputs/evals/`.
- [ ] 1.4 Unit-test aggregation on synthetic sample dicts for several encodings (no model calls); assert the table shape + that summarize_eval/progression are used.

## 2. Matrix orchestration

- [ ] 2.1 Add an orchestration layer that takes an encoding set (variant + map_detail) + model configs and runs each cell via the existing verifiers eval path, parameterizing the env by `variant`/`map_detail`, writing raw samples to `outputs/evals/`.
- [ ] 2.2 Make the encoding set + models configuration-driven (data, not code); default matrix = ASCII/IMG/IMG_TTY/JSON/TOON × {1 instruct LLM, 1 VLM}.
- [ ] 2.3 Test orchestration wiring with a stub runner (no real model calls) — assert each cell is dispatched with the right variant/map_detail.

## 3. Replayable rollout logs — CAPTURE (in scope; viewer deferrable to Group B)

- [ ] 3.1 Capture full multimodal content per turn: extend `_write_trace_entry` (+ the `env_response` call site) to record the `[image_url, text]` content (image data URI written to/linked from `outputs/evals/`), not just the flattened text. Existing text-encoding traces stay backward-compatible.
- [ ] 3.2 Human-viewable timeline: wire the harness rollouts to `legacy/replay.py` `TrajectoryRecorder` (rendered tty frames) so game state is replayable independent of encoding.
- [ ] 3.3 Document the on-disk replay-log format + a marked rendering entry point (the integration seam for Group B's `tools/launchpad` viewer). Provide a MINIMAL renderer (e.g. plain dump of both forms) behind that seam — the rich viewer is a Group B integration, not built twice here.
- [ ] 3.4 Tests: a turn with multimodal content captures the image (not elided); the minimal renderer reproduces text-form and image-form per turn from a recorded fixture; the log-format/seam is stable (documented keys present).

## 4. VLM config

- [ ] 4.1 Add a VLM eval config under `configs/eval/` mirroring the existing TOML shape so IMG/IMG_TTY are exercisable.

## 5. Verification

- [ ] 4.1 Run new tests in isolation; full suite failure set stays ⊆ the pre-existing baseline (7).
- [ ] 4.2 Document how to run a real benchmark (the operational follow-up: keys/budget) in the harness module docstring or a short README note.
