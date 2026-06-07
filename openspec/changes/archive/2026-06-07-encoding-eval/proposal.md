## Why

We have built five observation encodings — ASCII (`B1`), pixels (`IMG`,
`IMG_TTY`), and structured text (`JSON`, `TOON`, each at `full`/`minimal`) — to
answer one question: **which encoding does a model actually play NetHack best
from?** Nothing measures that yet. This change adds the benchmark harness that
runs the same task across all encodings and reports comparable metrics — roadmap
milestone **M3, the go/no-go gate** that should inform whether and how to invest
in further work (Group B). It is the split-out follow-up from
`structured-map-observation`.

## What Changes

- Add an **encoding-eval harness**: given an encoding set (variant + `map_detail`)
  and a set of model configs, run rollouts for each `(encoding, model)` cell,
  collect the rollout samples, and aggregate them into a per-encoding comparison
  table.
- **Reuse existing instrumentation**, not a new metrics stack:
  `tools/eval_instrument.py` (`summarize_eval`, `classify_failure`, `wilson_ci`,
  scout/descent extraction) and `nethack_harness/prompt/balrog.py`
  (`progression_score` / `progression_tier`).
- Report per cell: progression score/tier, max dungeon level reached, descent
  rate (with Wilson CI), scout coverage, steps-to-first-descent, tokens/turn, and
  $/run.
- Support at least one **instruct LLM** and at least one **VLM** in the matrix
  (the VLM is what makes IMG/IMG_TTY meaningful). Add a VLM endpoint config under
  `configs/eval/` since only instruct-LLM configs exist today.
- **Replayable rollout logs in two forms.** Every rollout SHALL be replayable as
  (a) a **human-viewable** game-state timeline and (b) the **exact form the model
  saw** each turn — text for ASCII/JSON/TOON, and the actual **image + text** for
  IMG/IMG_TTY. This requires capturing the *full multimodal content* per turn (the
  current trace writer stores only the text and elides the image), plus a viewer
  that renders both forms. The human-viewable timeline reuses the existing
  `legacy/replay.py` `Trajectory`/recorder; the LLM-input form extends the
  per-turn trace.
- The harness is **testable with mock rollout samples** (synthetic sample dicts →
  summarize → table) so CI does not require model calls.

## Capabilities

### New Capabilities
- `encoding-eval`: the benchmark harness — matrix orchestration over
  `(encoding, model)`, metric aggregation reusing `eval_instrument` + `balrog`,
  and a comparison-table output.

### Modified Capabilities
<!-- None. This consumes the existing variants/instrumentation; it does not change
     any variant's rendered bytes or the eval_instrument metrics. -->

## Impact

- **New** harness module (matrix runner + table builder), a replay **viewer**
  (human + LLM-input forms), and a VLM `configs/eval` entry; outputs land under
  `outputs/evals/`.
- **Modified** per-turn trace capture (`nethack_harness/helpers.py`
  `_write_trace_entry` + the `env_response` call site) to record the **full
  multimodal content** (including the image data URI for IMG/IMG_TTY), not just
  the flattened text.
- **Reuses** `tools/eval_instrument.py`, `nethack_harness/prompt/balrog.py`, the
  existing `configs/eval/*.toml` shape, `legacy/replay.py` (human-viewable
  timeline), and the verifiers eval path that already runs the env.
- **Dependencies**: none new for the harness code. Running a *real* benchmark
  needs model API keys + budget.
- **Out of scope (code)**: actually executing a full real benchmark across paid
  models is an **operational follow-up**, not part of this change; RL training;
  Group B (pysc2 interface, customizable game); changing any encoding's output.
