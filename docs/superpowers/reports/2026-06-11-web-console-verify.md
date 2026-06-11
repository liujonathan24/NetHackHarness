# Verification Report: web-console

Date: 2026-06-11
Mode: full (16 tasks, 1 capability, 15 changed files)
Base ref: `3a251d64b4bfab70684a0abd222a4a0bbdd4f9f2`

## Summary

| Dimension    | Status                              |
|--------------|-------------------------------------|
| Completeness | 16/16 tasks, 5/5 requirements built |
| Correctness  | 5/5 requirements covered + tested   |
| Coherence    | Followed design; 1 spec-text nit    |

**Final assessment: All checks passed. No critical issues. 1 SUGGESTION. Ready for archive.**

## Evidence

- **Tests:** `pytest environments/nethack/tests/ -q` → **73 passed** (includes `test_obs_creator.py` 29 + `test_vision_overlay.py`). The earlier 38 "failures" were a full `/tmp` (ENOSPC) infra condition, since cleared; not code-related.
- **Page smoke (Flask test_client):** `/`, `/map`, `/obs`, `/traces` all 200; `/catalog`, `/obs/metrics`, `/gifs`, `/reset`, `/step`, `/live`, `/traces` (JSON + HTML content-negotiated) all 200.
- **Legacy untouched:** `tools.launchpad.tui.app` still imports.

## Completeness — 16/16 tasks `[x]`

All sections (1 structure/theme, 2 landing, 3 map viewer, 4 obs creator, 5 tracer, 6 vision overlay, 7 verify) checked.

## Correctness — requirement → implementation

1. **Multi-page console + landing** — `tools/play_server.py` page routes `/`, `/map`, `/obs`, `/traces`; one `EngineEnv`; shared `tools/webconsole/static/console.css` (retro gray + pastel); `landing.html` = description + GIF gallery + 3 nav cards, no game widgets. ✓
2. **Map Viewer** — `map.html` + `console.js`: structured chars+colors+message+status, keyboard commands, grouped knob sidebar (Vision / Stat-based / Dungeon & spawns), bool switches + slider/editable numbers; live knobs via `/live`, reset knobs via `/reset` regenerate. ✓
3. **Observation Creator** — `/obs`, `GET /obs/metrics`, `POST /obs/plot`; reuses `tools/rollout_view` (`load_trace`, `series`, `register_metric`, `run_summary`/`aggregate` via `dashboard._agg_table`, `_svg_linechart`); safe AST evaluator for custom metric composition (no eval); path allow-list + builtin-collision + request-scoped registry isolation. Tested (29 cases). ✓
4. **Tracer** — `/traces` lists `.ndjson`, scrubber, per-turn map+status+reward+messages+LLM panes; web recordings replayable. ✓
5. **Vision overrides reversible** — `reveal_map`/`fog_of_war` as render-time obs overlays in fork `winrl.cc fill_obs` (no `gbuf` mutation); `/live` ctrl-R re-renders both directions. `test_vision_overlay.py` asserts reveal 1→0 drops obs cell count back and game state is unaffected. ✓

## Coherence

Implementation follows `design.md` and the Design Doc (reveal/fog as reversible obs overlay; multi-page Flask shell; Observation Creator wraps `tools/rollout_view`). Delta spec and design doc agree (no contradiction).

## SUGGESTION (non-blocking)

- The delta spec (`specs/web-console/spec.md` Requirement "Observation Creator") and the Design Doc name `register_custom_metric`, but the actual `tools/rollout_view.stats` API is `register_metric` — the named function never existed. The implementation correctly uses `register_metric`. Reconcile the spec/design text to `register_metric` during archive (main-spec sync). No code change needed.
