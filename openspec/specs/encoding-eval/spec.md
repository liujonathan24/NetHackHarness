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
- **THEN** each turn shows the actual image the model received (the captured PNG/data-URI), not a text-only elision, alongside the text block

#### Scenario: Full multimodal content is captured per turn
- **WHEN** a per-turn trace entry is written for an image-encoding rollout
- **THEN** it records the full multimodal content (image + text), so the LLM-input form can be reconstructed without re-running the rollout

#### Scenario: Viewer is a marked integration seam
- **WHEN** the rich replay rendering is built (now minimally, or later in Group B)
- **THEN** it reads the documented on-disk log format via a marked rendering entry point, so the viewer can move to Group B's `tools/launchpad` infrastructure without changing what was captured
