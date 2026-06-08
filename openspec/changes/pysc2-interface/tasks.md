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
