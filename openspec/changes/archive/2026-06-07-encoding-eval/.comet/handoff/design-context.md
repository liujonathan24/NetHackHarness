# Comet Design Handoff

- Change: encoding-eval
- Phase: design
- Mode: compact
- Context hash: c710e38e364d7650825be9f2161b1852fd2ad09aa0c8919deaeadf9a7e1aaa95

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/encoding-eval/proposal.md

- Source: openspec/changes/encoding-eval/proposal.md
- Lines: 1-66
- SHA256: c55f4de9de78febaa1cea5612037438e0766a56850b6f873809e98ce8cd8edb8

```md
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
```

## openspec/changes/encoding-eval/design.md

- Source: openspec/changes/encoding-eval/design.md
- Lines: 1-73
- SHA256: d0011d25b8a2aaf5ca93ece5e9aaa19152fe780a5f4cbf730624f33bf1d65fa2

```md
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
```

## openspec/changes/encoding-eval/tasks.md

- Source: openspec/changes/encoding-eval/tasks.md
- Lines: 1-28
- SHA256: ccc484e3e50c3f4d26921a8c6330bbb1a35b3a0400511da84a9bc84fba783337

```md
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
```

## openspec/changes/encoding-eval/specs/encoding-eval/spec.md

- Source: openspec/changes/encoding-eval/specs/encoding-eval/spec.md
- Lines: 1-89
- SHA256: 77fdaa512a5984a02d9c7fa7c2013d2ad9ae45caa9e1819948325e1979c28aae

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: Encoding comparison harness

The harness SHALL run the same NetHack task across a configurable set of
observation encodings (each a `variant` plus, for JSON/TOON, a `map_detail`
level) and across a configurable set of model configs, and produce a
per-encoding comparison of metrics. It SHALL parameterize the environment by
`variant` and `map_detail` per matrix cell and SHALL NOT change any variant's
rendered output.

#### Scenario: Runs the encoding matrix
- **WHEN** the harness is given an encoding set (e.g. ASCII, IMG, IMG_TTY, JSON, TOON) and ≥1 model config
- **THEN** it produces, for each `(encoding, model)` cell, the configured metrics

#### Scenario: Encoding set is configurable data
- **WHEN** an encoding is added to or removed from the matrix configuration
- **THEN** the harness runs the new set without code changes

### Requirement: Metrics reuse existing instrumentation

The harness SHALL compute its metrics by reusing `tools/eval_instrument.py`
(`summarize_eval`, `classify_failure`, `wilson_ci`, scout/descent extraction) and
`nethack_harness/prompt/balrog.py` (`progression_score` / `progression_tier`)
rather than re-implementing them. Reported metrics SHALL include at least:
progression score/tier, max dungeon level reached, descent rate with a Wilson
confidence interval, scout coverage, steps-to-first-descent, and tokens/turn.

#### Scenario: Aggregation uses the existing summarizer
- **WHEN** the harness aggregates a cell's rollout samples
- **THEN** it calls `summarize_eval` and the `progression_*` helpers, not a re-implemented metrics path

#### Scenario: Token cost reported per encoding
- **WHEN** the harness compares JSON-full vs JSON-minimal (or JSON vs TOON) on the same task
- **THEN** it reports tokens/turn for each so the cost trade-off is visible

#### Scenario: Missing usage data is marked, not guessed
- **WHEN** a model provider does not report token usage for a cell
- **THEN** the harness marks that cell's $/run as unavailable rather than fabricating a value

### Requirement: Mock-testable aggregation

The harness's aggregation layer SHALL be pure with respect to model calls: given a
list of rollout sample dicts, it produces the comparison table without invoking
any model. A VLM eval config SHALL be added under `configs/eval/` so the
pixel encodings are exercisable in a real run.

#### Scenario: Aggregation runs on mock samples
- **WHEN** the aggregation layer is given synthetic rollout sample dicts for several encodings
- **THEN** it produces the per-encoding comparison table with no model calls

#### Scenario: Comparison table emitted
- **WHEN** the harness finishes aggregating a matrix
- **THEN** it writes a structured per-encoding comparison table under `outputs/evals/`

### Requirement: Replayable rollout logs (human + LLM-input forms)

Every rollout produced or consumed by the harness SHALL be **captured** with
enough information to be replayed in two forms: (a) a **human-viewable**
game-state timeline (the dungeon state per turn, independent of how it was
encoded), and (b) the **exact content the model received** each turn. For text
encodings (ASCII / JSON / TOON) the captured LLM-input form SHALL reproduce the
per-turn message text; for the image encodings (IMG / IMG_TTY) it SHALL include
the actual image the model saw (the captured PNG/data-URI, not a text elision)
alongside the text. Capturing this data is in scope for this change; the **rich
rendering viewer is a deferrable integration** with Group B's viewing
infrastructure (`tools/launchpad`) and SHALL be exposed behind a documented
integration seam (a stable on-disk log format + a marked rendering entry point),
so a minimal renderer here can be superseded by Group B without re-capturing.

#### Scenario: Human-viewable timeline
- **WHEN** a recorded rollout is replayed in human-viewable form
- **THEN** each turn shows the game state (e.g. the rendered map/tty and message), independent of the rollout's observation encoding

#### Scenario: LLM-input form for a text encoding
- **WHEN** a rollout that used a text encoding (ASCII / JSON / TOON) is replayed in LLM-input form
- **THEN** each turn shows the exact message text the model received

#### Scenario: LLM-input form preserves the image for pixel encodings
- **WHEN** a rollout that used IMG or IMG_TTY is replayed in LLM-input form
```

Full source: openspec/changes/encoding-eval/specs/encoding-eval/spec.md

