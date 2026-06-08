---
comet_change: pysc2-interface
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-07-pysc2-interface
status: final
---

# pysc2-interface + rollout views — technical design

> Canonical requirements: the OpenSpec delta specs under
> `openspec/changes/pysc2-interface/specs/`. This is the *how*.

## Summary

Group B agent tooling: a typed **`nethack_interface`** package (PySC2-style
ObservationSpec + ActionSpec + Env wrapper, RL-ready) plus a **shared HTML
rollout-view layer** that serves both a live rollout stepper and a recorded
replay viewer. The HTML approach (user's call) works locally and remotely and
gives full image fidelity for the pixel encodings.

## Confirmed decisions

| Decision | Choice |
| --- | --- |
| ActionSpec | Derived from `SkillRegistry._schemas` (single source of truth) + raw NLE escape hatch |
| Action execution | Typed actions via the existing `skills.call(...)` dispatch (parity); raw via `env.step(int)` |
| Observation | Flat typed `Observation` dataclass (map model + status/inventory/character feature layers); schema via dataclass-field introspection |
| `available_actions` | Static action set for v1; per-state legality deferred to RL |
| Package | `nethack_interface` (uv workspace member over `nethack_core`) |
| Rollout views | **One shared HTML rollout-view core**: live = local web server stepping a rollout; replay = static HTML export. Both render per-turn game-state + LLM-input with inline images |
| Live stepper modes | **Manual/scripted** (keyless) AND **model-driven** (calls a model per turn) |
| Build order | interface first → then the rollout-view layer (live + replay) |

## Components

### 1. `nethack_interface` package
- `Observation` (flat dataclass): `player`, `entities`, `grid`, `status`,
  `inventory`, `character` — built via `build_map_model` + `StructuredObservation`.
  `Observation.spec()` introspects the dataclass fields → the schema descriptor.
- `ActionSpec`: reads `SkillRegistry._schemas` → `{name: arg_schema}`; a typed
  `Action` carries `name` + args; a `RawAction(index:int)` escape hatch.
- `NetHackInterface`: `reset() -> Observation`; `step(action) -> (Observation,
  reward, done, info)`. Typed actions execute via `skill_registry.call(name,
  env, obs, **args)` (stepping the env through the returned action list +
  aggregating reward); `RawAction` via `NetHackCoreEnv.step(int)`. Reuses core
  seeding/stepping.

### 2. Shared HTML rollout-view core (`tools/launchpad` or a new view module)
- `render_turn(turn) -> html` and `render_run(turns) -> html`: per turn, two
  columns — **game-state** (raw_grid/tty + message) | **LLM-input**
  (`rendered_user_content`: text, and inline `<img>` from the captured PNG for
  image encodings). Self-contained HTML (images inlined or relative-linked).
- **Replay viewer**: reads a recorded run via the encoding-eval seam
  (`REPLAY_LOG_KEYS` + `rendered_user_content` + `images/`) → `render_run` → a
  static `replay.html`. Supersedes the encoding-eval minimal renderer; launchpad
  TUI shows text forms + opens the HTML.
- **Live stepper**: a tiny local web server that drives the harness rollout one
  turn at a time (reusing `env_response`), rendering each turn via `render_turn`
  and serving it; **manual mode** exposes step/action controls (no model calls),
  **model mode** calls a model per turn. Variant/prompt selectable.

## Data flow

```
                         ┌── nethack_interface (typed obs/action/env, RL-ready)
nethack_core ────────────┤
                         └── harness env_response (rollout)
                                      │ per-turn turn dict (raw_grid + rendered_user_content + images)
                                      ▼
                         shared HTML rollout-view core: render_turn / render_run
                              │                                  │
                live stepper (local server, manual|model)   replay viewer (static replay.html)
                              │                                  │
                         browser (local or remote)          browser + launchpad TUI "open HTML"
```

## Risks / Trade-offs

- [Scope: 3 capabilities in one change] → build interface first, then the shared
  HTML layer (live + replay reuse one renderer, so the two views are cheap once
  the core exists).
- [Live stepper drives env_response] → reuse the public rollout path; no forked
  rollout logic.
- [HTML server security] → bind localhost; it's a dev tool.
- [ActionSpec runtime-typed] → accept; static wrappers later for RL.

## Testing strategy

- Interface: Observation carries map model + status/inventory; `spec()` reports
  the schema; ActionSpec lists core actions from the registry + accepts a raw
  index; `reset/step` return typed obs and execute via dispatch (mock/short).
- HTML core: `render_turn`/`render_run` on a recorded fixture produce both
  columns; image turn embeds the PNG; reads the seam unchanged.
- Live stepper: stepping advances exactly one turn and surfaces obs+action;
  manual mode needs no model; reuses the rollout path.

## Out of scope

`customizable-game` (Group B part 2); re-platforming `nh` onto the interface; RL
training; per-state action legality.
