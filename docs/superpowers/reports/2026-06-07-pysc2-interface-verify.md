# Verification Report: pysc2-interface (Group B part 1)

Date: 2026-06-07 · Mode: full · Branch: nethack-interface

## Summary

| Dimension | Status |
|---|---|
| Completeness | 17/17 tasks checked; 3/3 capabilities implemented |
| Correctness | 14/14 spec scenarios covered (committed tests + documented inline real-env verification) |
| Coherence | Matches Design Doc + delta specs (typed interface, shared HTML rollout-view, HTML-unified live+replay); no drift |

## Completeness

- `tasks.md`: 17/17 `[x]`.
- Capabilities: `pysc2-interface` → `nethack_interface/` package (observation/actions/env);
  `replay-viewer` → `tools/rollout_view/{html,replay_export,open}.py`;
  `live-rollout-stepper` → `tools/rollout_view/live_server.py`.

## Correctness — scenario → evidence (14/14)

**pysc2-interface**
| Scenario | Evidence |
|---|---|
| Observation carries map model + status/inventory | `test_observation_from_raw_carries_map_and_status` |
| Observation has a declared schema | `test_observation_spec_declares_fields` |
| Core actions typed, derived from the registry | `test_action_spec_derives_core_actions_from_registry` |
| Raw action escape hatch | `test_typed_action_and_raw_action` + `test_interface_env` (RawAction steps a real env) |
| Reset returns a typed observation | `test_reset_and_step` (real seeded env) |
| Step applies a typed action via skill dispatch | `test_reset_and_step` (`Action("search")`); Task-4 review confirmed `_to_action_indices`+step parity with `env_response` |
| Reuses the core env | `test_reset_and_step` (delegates to `NetHackCoreEnv`) |

**replay-viewer**
| Scenario | Evidence |
|---|---|
| Human-viewable timeline | `test_render_turn_two_columns_text_and_image` (raw_grid column) |
| LLM-input form with images | same (text + `<img src=path>` for the image turn) |
| Reads the documented seam, no re-capture | `test_export_replay_html_writes_self_contained_file` (reads `*.ndjson` + image paths) |
| Launchpad integration (open HTML) | `test_open_replay_html_exports_without_browser` |

**live-rollout-stepper**
| Scenario | Evidence |
|---|---|
| Step through a rollout turn-by-turn | `test_manual_step_advances_one_turn` (real env; one turn) |
| Variant/prompt is selectable | inline-verified against a real env: B1 `rendered_user_content` is a real render (1452 chars, contains `=== STATUS ===`, no error guard); the stepper takes a `variant` arg routed through `resolve_spec(...).turn_template` |
| Reuses the harness rollout path | `LiveStepper` drives `NetHackInterface` (which uses the skill dispatch + `_to_action_indices` parity path); manual + model modes inline-verified (model policy called, turn advanced) |

## Test evidence

- New tests in isolation: 10 passed (import 1, observation 2, actions 2, env 1, html 2, open 1, live 1).
- Full suite: **385 passed / 7 failed** — the 7 are EXACTLY the pre-existing baseline (`test_integration::test_success_reward_zero_then_one` + 6 × `test_rewards`, ordering pollution). Zero new failures.
- `nethack_interface` imports cleanly and is a resolvable uv-workspace member.

## Security

No hardcoded secrets. The live server binds `127.0.0.1` (localhost dev tool). The HTML core escapes LLM text + image `src`; the game-state column renders NLE's own ASCII tty verbatim in `<pre>` (game output, not untrusted input).

## Coherence / scope

- Implemented per the Design Doc: typed `nethack_interface` (Observation/ActionSpec-from-registry/Env-wrapper-via-dispatch+raw), shared HTML rollout-view core, replay-viewer (static export over the seam) + live stepper (localhost, manual + model). Action execution is true parity with `env_response` (Task-4 review).
- Out of scope as designed: `customizable-game` (Group B part 2, separate change); deep launchpad Textual replay-screen wiring (light follow-up — the headless `open_replay_html` + live server cover v1); RL training; per-state action legality.

## Issues

- CRITICAL / WARNING: none.
- SUGGESTION (non-blocking): the env wrapper omits harness-policy layers (menu auto-dismiss, mid-sequence halts, scout/journal bookkeeping) — intentional for a thin RL wrapper, flagged in the Task-4 review; revisit if full harness behavioral parity is needed for RL. The live server's real (non-pytest) invocation needs `tools/` + `environments/nethack` on `PYTHONPATH` (or `uv sync`) — document in usage.

## Assessment

No critical/warning issues. All 14 scenarios covered, full suite green modulo the documented baseline. **Ready for archive.**
