## Context

`tools/eval_instrument.py` already turns a list of rollout sample dicts into
summary metrics (`summarize_eval`), with failure classification, descent
detection, scout-window deltas, and `wilson_ci`. Eval configs under
`configs/eval/*.toml` are `vf-eval`-style (`model`, `num_examples`,
`rollouts_per_example`, `max_tokens`, `[[eval]] env_id`). The verifiers env
(`environments/nethack/nethack.py`) is selected by a `variant` kwarg (and
`map_detail`), and produces rollout samples consumed by the instrument.
`nethack_harness/prompt/balrog.py` computes `progression_score` /
`progression_tier`. So the missing piece is only the **orchestration + per-encoding
aggregation + table**, not metrics or rollout execution.

## Goals / Non-Goals

**Goals:**
- A harness that, given an encoding set and model configs, runs (or accepts the
  outputs of) the `(encoding, model)` matrix and produces a per-encoding
  comparison table reusing the existing instrument + progression metrics.
- Testable with mock rollout samples (no model calls in CI).
- One VLM config added so IMG/IMG_TTY are exercisable.

**Non-Goals:**
- No new metrics stack (reuse `eval_instrument`). No RL training. No change to any
  variant's output. Not running a paid real benchmark (operational follow-up).

## Decisions (high-level; deep design in /comet-design)

- **Separate orchestration from summarization.** A `run` layer executes the
  matrix (parameterizing the env by `variant` + `map_detail` per cell, via the
  existing verifiers eval path) and writes raw samples to `outputs/evals/`; an
  `aggregate` layer loads samples and calls `summarize_eval` + `progression_*`
  per cell. The aggregate layer is pure (mock-testable).
- **Encoding set is data, not code.** The matrix (which variants, which detail
  levels, which models) is a config/argument, so adding/removing an encoding
  doesn't touch the harness.
- **Table is the artifact.** Output is a structured comparison (encoding ×
  metric) plus a human-readable table; emit to `outputs/evals/`.
- **VLM config** added under `configs/eval/` mirroring the existing TOML shape.
- **Replay = capture now, rich viewer later (Group B integration).** The durable,
  must-have-now part is **capturing** enough to replay both forms; the rich
  rendering UI ties into Group B's viewing infrastructure (`tools/launchpad`), so
  we do not build a full viewer twice.
  - (a) Human-viewable timeline reuses `legacy/replay.py`
    (`Trajectory`/`TrajectoryRecorder` — rendered tty frames), inspectable
    independent of encoding.
  - (b) LLM-input form extends the per-turn trace: `_write_trace_entry` currently
    stores `rendered_user_message` as flattened text (image elided for IMG).
    Capture the **full multimodal content** (`[image_url, text]`, including the
    data URI; image bytes written to/linked from `outputs/evals/` to keep trace
    lines small) so the exact VLM input can be reconstructed.
  - **Integration seam:** a documented on-disk log format + a marked rendering
    entry point. A *minimal* renderer (plain dump of both forms) ships here; the
    rich viewer is a Group B task reading the same format — no re-capture needed.

## Risks / Trade-offs

- [Real runs need budget/keys] → split: build + unit-test the harness now (mock
  samples); a separate operational step runs the paid matrix.
- [Token/$ accounting] → derive tokens/turn from rollout sample metadata if
  present; if a provider doesn't report usage, mark $/run as unavailable rather
  than guess.
- [VLM rollout cost/latency] → keep the default matrix small (few episodes) and
  make episode count a config knob.

## Open Questions (for /comet-design)

- Exact rollout-sample schema the orchestration writes vs. what `summarize_eval`
  expects (align to the existing format).
- Whether to shell out to the existing `vf-eval`/prime eval CLI per cell or drive
  the env in-process.
- Which specific VLM + instruct LLM to put in the default config.
- Table format (markdown / CSV / JSON) and where under `outputs/evals/`.
