# Comet Design Handoff

- Change: pysc2-interface
- Phase: design
- Mode: compact
- Context hash: 34a89efb1e6432812dbd822c609d5d6ee6ac8d570202ff0a148556ff97c68dd7

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/pysc2-interface/proposal.md

- Source: openspec/changes/pysc2-interface/proposal.md
- Lines: 1-57
- SHA256: 47d42212e16b69bbce5ed7d8e121c3694881aed930021e2bba89eb6bbaded224

```md
## Why

Group B gives the program its agent-facing tooling. Two needs converge:

- **Now (testing loop):** the user iterates by opening a rollout interactively,
  swapping prompts/variants, launching evals, occasionally adding skills, and
  tweaking the observation display — then, once a high baseline is found, starts
  RL. This wants a *live rollout stepper* and a *rich replay viewer* (to watch
  and inspect exactly what the model sees).
- **For RL (soon):** a stable, typed **PySC2-style interface** — a fixed
  ObservationSpec + ActionSpec + env wrapper — so a learning algorithm has a
  defined action space to act over and a tensor-shaped observation to consume.

This change builds **both**: the typed interface (RL-ready) and the inspection
tooling (testing-ready). It is Group B part 1 of the roadmap.

## What Changes

- Add a typed **`nethack_interface`** workspace package (PySC2-style): a typed
  **ObservationSpec** (canonical map model entities+grid + status/inventory/
  character as declared feature layers), a typed **ActionSpec** (the skill action
  set + a raw NLE escape hatch), and a thin typed **Env wrapper**
  (`reset()/step(action)`) over `NetHackCoreEnv`.
- Add a **live rollout stepper**: run a chosen model + variant/prompt and step
  through its turns one at a time, watching the observation the model receives
  and the action it takes (pause / inspect). Reuses the existing harness rollout
  path.
- Add the **rich replay viewer**: read the encoding-eval `REPLAY_LOG_KEYS` seam
  (per-turn `rendered_user_content` + `images/`) and render a recorded rollout in
  both the human-viewable game-state form and the exact LLM-input form — with the
  actual image for IMG/IMG_TTY via a self-contained **HTML replay export**;
  `tools/launchpad`'s TUI shows the text forms + opens the HTML.

## Capabilities

### New Capabilities
- `pysc2-interface`: typed ObservationSpec + ActionSpec + Env wrapper package over
  `nethack_core` (the RL-ready structured interface).
- `live-rollout-stepper`: step a model rollout live (obs in / action out, per turn).
- `replay-viewer`: rich rollout replay (HTML + launchpad) of both forms with images.

### Modified Capabilities
<!-- None. The ad-hoc nh namespace, skills, and the encoding-eval minimal renderer
     are unchanged; this adds the typed package + the two inspection tools. -->

## Impact

- **New** workspace package `nethack_interface/` (uv member), depending on
  `nethack_core` (`map_model`, `observations`, `env`) + reusing the schema'd
  action vocabulary in `nethack_harness/tools/skills.py`.
- **New**/extended `tools/launchpad` code: the live stepper + the rich replay
  viewer (reads `REPLAY_LOG_KEYS`, emits HTML).
- **Reuses** the harness rollout path (`environments/nethack/nethack.py`
  env_response + `prompt_spec` variants), the encoding-eval seam
  (`tools/encoding_eval/replay.py`), and launchpad's trace plumbing.
- **Out of scope (separate sibling changes):** `customizable-game` (Group B part
  2); re-platforming the `nh` namespace onto the interface; RL training itself.
```

## openspec/changes/pysc2-interface/design.md

- Source: openspec/changes/pysc2-interface/design.md
- Lines: 1-60
- SHA256: f5411aa528a5dfed8c60f7749ef666ff7c2ae2e5b627e7da465cd556394c263b

```md
## Context

`NetHackCoreEnv` (`nethack_core/env.py`) is gym-style (`reset()`,
`step(action:int)`, `action_space`); `nethack_core` has `StructuredObservation` +
`map_model` (MapModel/Entity/build_map_model). `skills.py` `SkillRegistry`
exposes `_schemas` (name→schema) + `call(...)` dispatch — the action vocabulary +
execution. The harness rollout loop is `environments/nethack/nethack.py`
`env_response`. `tools/launchpad` is a Textual TUI (Launch/Harness/Traces/Train +
`core/{live,traces,legacy_trace}.py`) — the iteration hub. The encoding-eval seam
(`REPLAY_LOG_KEYS`, per-turn `rendered_user_content` + `images/`) is the replay
data source.

## Goals / Non-Goals

**Goals:**
- A typed, RL-ready interface package (`nethack_interface`): ObservationSpec,
  ActionSpec, Env wrapper, over `nethack_core`.
- A live rollout stepper to watch a model play turn-by-turn.
- A rich replay viewer (both forms, real images) over the encoding-eval seam.

**Non-Goals:**
- Not the customizable game. Not re-platforming `nh`. Not RL training. No change
  to existing harness/skills behavior or encoding outputs.

## Decisions (high-level; deep design in /comet-design)

- **`nethack_interface` package** over `nethack_core` only.
  - ObservationSpec: a flat typed `Observation` dataclass (map model + status +
    inventory + character feature layers) + a schema descriptor.
  - ActionSpec: derived from the `SkillRegistry` schemas (single source of truth,
    no drift) + a raw NLE escape hatch. Static typed convenience wrappers can be
    layered later.
  - Env wrapper: typed `reset()/step(action)` that executes typed actions via the
    existing `skills.call(...)` dispatch (behavioral parity with the harness) and
    raw actions via `env.step(int)`.
- **Live rollout stepper** drives the existing harness rollout one turn at a time
  (reuse `env_response`), surfacing the per-turn observation (the model's input)
  and the chosen action; a thin controller with pause/step.
- **Replay viewer** reuses launchpad's trace plumbing; for image fidelity it emits
  a self-contained **HTML** replay (text + inline `<img>` from the captured PNGs,
  both forms); the TUI shows text forms + opens the HTML. Reads the documented
  seam — no new capture format.

## Risks / Trade-offs

- [Scope: 3 capabilities] → flag at open review; can split into (interface) and
  (stepper + viewer) if preferred. Interface is the RL-foundational piece; the two
  tools are the testing pieces.
- [ActionSpec runtime-typed (schema dicts) not static] → accept; static wrappers
  later. Avoids drift now.
- [Live stepper coupling to env_response] → drive via the public rollout path; do
  not fork env_response logic.
- [HTML viewer vs TUI images] → HTML for fidelity; TUI stays text + launch.

## Open Questions (for /comet-design)

- Exact ObservationSpec feature-layer list + schema descriptor shape.
- ActionSpec: how `available_actions` (per-state legality) is expressed.
- Live stepper: in-TUI (launchpad screen) vs a standalone CLI stepper first.
- HTML replay layout (per-turn columns: game-state | LLM-input).
```

## openspec/changes/pysc2-interface/tasks.md

- Source: openspec/changes/pysc2-interface/tasks.md
- Lines: 1-36
- SHA256: 62e80b76b937706fa2b188be762893723336f4609c3a724c82a532fa691b0cc9

```md
## 1. nethack_interface package scaffold

- [ ] 1.1 Create the `nethack_interface` workspace package (pyproject + `__init__`) depending on `nethack_core`; add to `[tool.uv.workspace] members`.

## 2. Observation spec

- [ ] 2.1 Typed `Observation` (player, entities, grid, status, inventory, character) built from `build_map_model` + `StructuredObservation`.
- [ ] 2.2 ObservationSpec schema descriptor (per-feature-layer field names/types).
- [ ] 2.3 Tests: observation carries the map model + status/inventory; spec reports the schema.

## 3. Action spec

- [ ] 3.1 Typed action set derived from the SkillRegistry `_schemas` (core actions + arg schemas) + a raw NLE escape hatch.
- [ ] 3.2 Tests: core actions listed with arg schemas sourced from the registry; raw action index accepted.

## 4. Typed env wrapper

- [ ] 4.1 `NetHackInterface.reset() -> Observation` and `.step(action) -> (Observation, reward, done, info)` over `NetHackCoreEnv`; typed actions via skill dispatch, raw via `env.step`.
- [ ] 4.2 Tests: reset returns typed obs; step applies a typed action via dispatch + returns next typed obs; delegates to core env.

## 5. Live rollout stepper

- [ ] 5.1 Interactive driver to run a model + variant and step the rollout one turn at a time (reuse env_response), surfacing the per-turn observation + chosen action, with step/pause.
- [ ] 5.2 Variant/prompt selectable; the shown observation reflects the chosen encoding.
- [ ] 5.3 Tests: stepping advances exactly one turn and surfaces obs+action; reuses the rollout path.

## 6. Rich replay viewer

- [ ] 6.1 Read a recorded run via `REPLAY_LOG_KEYS` (rendered_user_content + images/); emit a self-contained HTML replay rendering both forms with inline images for pixel encodings.
- [ ] 6.2 Launchpad TUI integration: show text forms + open the HTML replay.
- [ ] 6.3 Tests: viewer loads a recorded fixture → both forms; image turn embeds the PNG; no change to capture format.

## 7. Verification

- [ ] 7.1 New tests pass in isolation; full suite failure set stays ⊆ the pre-existing baseline (7).
- [ ] 7.2 `nethack_interface` imports cleanly + is a resolvable workspace member; launchpad viewer + stepper run.
```

## openspec/changes/pysc2-interface/specs/live-rollout-stepper/spec.md

- Source: openspec/changes/pysc2-interface/specs/live-rollout-stepper/spec.md
- Lines: 1-22
- SHA256: b8dcfbc7a0189c08b12f6d2904fdc71edbb6bfc5389944c6d73e08dcd6fd6ef6

```md
## ADDED Requirements

### Requirement: Step a model rollout live

The harness SHALL provide an interactive driver that runs a chosen model with a
chosen variant/prompt and steps through the rollout one turn at a time. At each
step it SHALL surface the observation the model received (its exact input) and
the action the model took, and SHALL let the user advance (step), pause, and
inspect. It SHALL drive the existing harness rollout path (the env_response loop
+ the variant's rendering) rather than reimplementing rollout logic.

#### Scenario: Step through a rollout turn-by-turn
- **WHEN** the user starts a live rollout with a model + variant and advances one step
- **THEN** it runs exactly one turn and shows the observation the model received and the action it took

#### Scenario: Variant/prompt is selectable
- **WHEN** the user starts a live rollout
- **THEN** they can choose which variant/prompt is used (e.g. B1 / IMG / JSON / TOON), and the observation shown reflects that encoding

#### Scenario: Reuses the harness rollout path
- **WHEN** the stepper advances a turn
- **THEN** it uses the existing env_response rollout path (no forked rollout logic)
```

## openspec/changes/pysc2-interface/specs/pysc2-interface/spec.md

- Source: openspec/changes/pysc2-interface/specs/pysc2-interface/spec.md
- Lines: 1-54
- SHA256: 8b1e85b994943dd86b87619b20f560ef99600ce4e9c22c49356d596804955e7c

```md
## ADDED Requirements

### Requirement: Typed observation spec

The interface SHALL provide a typed structured observation, built on the
canonical map model, exposing the player position, the typed entity list (with
coordinates and per-kind attributes), the compact grid, and the status,
inventory, and character blocks as declared feature layers (each with a typed
schema). It SHALL be derived from `nethack_core` (`build_map_model` +
`StructuredObservation`), not re-parsed from raw NLE.

#### Scenario: Observation carries the map model + status/inventory
- **WHEN** an observation is produced for a turn
- **THEN** it exposes the player position, the entity list with coordinates, the grid, and the status / inventory / character blocks

#### Scenario: Observation has a declared schema
- **WHEN** the observation spec is queried
- **THEN** it reports the typed shape of each feature layer (field names/types), independent of any particular turn

### Requirement: Typed action spec

The interface SHALL provide a typed action set derived from the schema'd skill
registry (so it cannot drift from the real actions) covering at least the core
actions (move, attack, descend, search, pickup, move_to), each with typed
arguments, plus a raw NLE action-index escape hatch.

#### Scenario: Core actions are typed, derived from the registry
- **WHEN** the action spec is queried
- **THEN** it lists the core actions with their argument schemas, sourced from the skill registry (not a hand-maintained duplicate)

#### Scenario: Raw action escape hatch
- **WHEN** an agent needs an action outside the typed set
- **THEN** it can submit a raw NLE action index accepted by the underlying env

### Requirement: Typed env wrapper

The interface SHALL provide a thin env wrapper over `NetHackCoreEnv` exposing
`reset() -> Observation` and `step(action) -> (Observation, reward, done, info)`,
returning the typed observation and accepting a typed or raw action. Typed
actions SHALL execute via the existing skill dispatch (behavioral parity with the
harness); raw actions via `NetHackCoreEnv.step`. Existing core behavior
(seeding, stepping) SHALL be reused, not reimplemented.

#### Scenario: Reset returns a typed observation
- **WHEN** the wrapper is reset
- **THEN** it returns a typed observation built from the core env's initial state

#### Scenario: Step applies a typed action via skill dispatch
- **WHEN** a typed action is passed to step
- **THEN** the wrapper executes it through the same skill dispatch the harness uses and returns the next typed observation, reward, done, and info

#### Scenario: Reuses the core env
- **WHEN** the wrapper steps or resets
- **THEN** it delegates to `NetHackCoreEnv` (no reimplementation of NLE stepping/seeding)
```

## openspec/changes/pysc2-interface/specs/replay-viewer/spec.md

- Source: openspec/changes/pysc2-interface/specs/replay-viewer/spec.md
- Lines: 1-28
- SHA256: 0c3f954e22841cd37638b410e94b0d57df938c24bafddc058690d4035546015e

```md
## ADDED Requirements

### Requirement: Rich rollout replay viewer

The harness SHALL provide a rich replay viewer that reads a recorded rollout via
the documented encoding-eval seam (`REPLAY_LOG_KEYS` + the per-turn NDJSON trace
with `rendered_user_content` + the `images/` directory) and renders it in two
forms: a human-viewable game-state timeline and the exact LLM-input form per
turn. For image encodings (IMG / IMG_TTY) the LLM-input form SHALL display the
actual captured image (from the referenced PNG) — not a text elision — via a
self-contained HTML replay export. The viewer SHALL read the same on-disk format
the encoding-eval minimal renderer documented (no new capture format).

#### Scenario: Renders the human-viewable timeline
- **WHEN** a recorded rollout is opened in human-viewable mode
- **THEN** it shows the game-state timeline (per-turn map/tty + message) across turns

#### Scenario: Renders the exact LLM-input form with images
- **WHEN** a rollout that used an image encoding is opened in LLM-input mode
- **THEN** each turn shows the text the model received and the actual captured image inline (HTML export), not a text-only elision

#### Scenario: Reads the documented seam without re-capture
- **WHEN** the viewer loads a run directory produced by the encoding-eval harness
- **THEN** it consumes the `REPLAY_LOG_KEYS` trace fields + `images/` directory directly, requiring no changes to how rollouts are captured

#### Scenario: Launchpad integration
- **WHEN** the user opens a recorded run in the launchpad TUI
- **THEN** the TUI shows the text forms and offers to open the self-contained HTML replay for full image fidelity
```

