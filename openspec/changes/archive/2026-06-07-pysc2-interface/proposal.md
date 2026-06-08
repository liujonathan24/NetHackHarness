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
