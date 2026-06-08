## 1. nethack_interface package scaffold

- [x] 1.1 Create the `nethack_interface` workspace package (pyproject + `__init__`) depending on `nethack_core`; add to `[tool.uv.workspace] members`.

## 2. Observation spec

- [x] 2.1 Typed `Observation` (player, entities, grid, status, inventory, character) built from `build_map_model` + `StructuredObservation`.
- [x] 2.2 ObservationSpec schema descriptor (`observation_spec()` via dataclass-field introspection).
- [x] 2.3 Tests: observation carries the map model + status/inventory; spec reports the schema.

## 3. Action spec

- [x] 3.1 Typed action set (`Action`/`RawAction` + `action_spec()`) derived from the SkillRegistry `_schemas` + a raw NLE escape hatch.
- [x] 3.2 Tests: core actions listed with arg schemas sourced from the registry; raw action index accepted.

## 4. Typed env wrapper

- [x] 4.1 `NetHackInterface.reset() -> Observation` and `.step(action) -> (Observation, reward, done, info)` over `NetHackCoreEnv`; typed actions via skill dispatch (with `_to_action_indices` normalization, true parity with env_response), raw via `env.step`.
- [x] 4.2 Tests: reset returns typed obs; step applies a typed action via dispatch + returns next typed obs (against a real seeded env); delegates to core env.

## 5. Shared HTML rollout-view core + replay export

- [x] 5.1 `tools/rollout_view/html.py` `render_turn`/`render_run` (per-turn two columns: game-state raw_grid | LLM-input `rendered_user_content` with inline `<img>` for pixel encodings).
- [x] 5.2 `replay_export.export_replay_html(run_dir)` — static self-contained HTML over the `REPLAY_LOG_KEYS` seam (no re-capture). Supersedes the encoding-eval minimal renderer.
- [x] 5.3 Tests: both columns rendered; image turn embeds the PNG; loads `*.ndjson`.

## 6. Live rollout stepper

- [x] 6.1 `tools/rollout_view/live_server.py` `LiveStepper` (`current_turn`/`step_once`) driving a `NetHackInterface`; renders the chosen variant's obs via `resolve_spec(...).turn_template` + raw_grid from tty; manual (keyless) AND model (`policy(obs)->action`) modes; localhost `serve()` + `__main__`.
- [x] 6.2 Variant/prompt selectable (the shown observation reflects the chosen encoding).
- [x] 6.3 Tests: stepping advances exactly one turn and surfaces obs+action (real env); model mode calls the policy; B1 render is real (not the error guard).

## 7. Launchpad open-HTML affordance + verification

- [x] 7.1 `tools/rollout_view/open.py` `open_replay_html(run_dir)` — export the HTML replay + open it in the browser (the launchpad full-image-fidelity path; TUI shows text forms).
- [x] 7.2 New tests pass in isolation (10); full suite 385 passed / 7 failed (== pre-existing baseline; zero new failures).
- [x] 7.3 `nethack_interface` imports cleanly + is a resolvable workspace member.

<!-- NOTE: deep launchpad Textual-screen wiring (a dedicated replay screen) is left
     as light follow-up; the headless open_replay_html affordance + the live server
     cover the v1 viewing need. -->
