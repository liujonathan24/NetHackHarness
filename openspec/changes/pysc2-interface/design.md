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
