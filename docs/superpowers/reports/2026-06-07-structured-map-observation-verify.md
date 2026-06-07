# Verification Report: structured-map-observation (Group A)

Date: 2026-06-07 · Mode: full · Branch: structured-map-observation

## Summary

| Dimension | Status |
|---|---|
| Completeness | 10/10 tasks checked; 3/3 capabilities implemented |
| Correctness | 15/15 spec scenarios covered by tests |
| Coherence | Matches Design Doc + delta specs (detail flag, rich schema, eval split all consistent); no drift |

## Completeness

- `tasks.md`: 10/10 `[x]`, 0 incomplete.
- Capabilities: `canonical-map-model` → `nethack_core/map_model.py` (both copies); `structured-map-observation` → `nethack_harness/prompt/map_encoders.py` + `prompt_spec.py` (JSON/TOON variants, `map_detail`) + `nethack.py` (flag threading); `code-interpretable-map` → `code_mode.py` (`MapView`/`nh.map`) + `nethack.py` (raw_obs wiring).

## Correctness — scenario → test (15/15)

| Capability / Scenario | Test |
|---|---|
| map-model: monster + rich attrs | `test_monster_entity_has_species_and_pet_flag` |
| map-model: item + object class | `test_item_entity_has_class` |
| map-model: stairs/features classified | `test_stairs_classified_with_coords` |
| map-model: player position | `test_player_position` |
| map-model: built from obs pipeline | (build_map_model uses raw obs + reuses StructuredObservation; exercised across model tests) |
| (extra) trap surfaced | `test_trap_entity_surfaced` |
| (extra) grid RLE | `test_grid_is_rle_string` |
| obs: JSON serializes model | `test_json_full_has_entities_and_grid`, `test_json_variant_emits_json_text` |
| obs: TOON more compact | `test_toon_deterministic_and_smaller_than_json` |
| obs: existing variants unchanged | regression (`test_obs_compaction`, `test_balrog`, `test_image_variants`) |
| obs: full detail emits rich + grid | `test_json_full_has_entities_and_grid` |
| obs: minimal trims attrs + grid | `test_json_minimal_trims_attrs_and_grid`, `test_map_detail_minimal_smaller_than_full` |
| obs: in-repo TOON deterministic | `test_toon_deterministic_and_smaller_than_json` |
| code-map: query by coordinate | `test_at_returns_entity` |
| code-map: convenience accessors | `test_kind_accessors` |
| code-map: read-only | `test_read_only_entities_copy` |

## Test evidence

- New tests (4 files) in isolation: 14 → now 16 passed (added stairs + read-only).
- Prompt/code regression: 81 passed.
- Full suite: **364 passed / 7 failed**. The 7 are EXACTLY the pre-existing baseline (`test_integration::test_success_reward_zero_then_one` + 6 × `test_rewards`, ordering pollution; pass in isolation). Zero new failures.

## Security

No hardcoded secrets; no new `exec`/`unsafe` surfaces (the code-mode executor was extended read-only with `nh.map`; `run_user_code` gained a `raw_obs` kwarg, no new execution capability).

## Coherence / scope

- Design decisions all reflected consistently: `map_detail` config flag (full/minimal), rich-where-derivable entity schema (disposition omitted), in-repo TOON, eval split out. Delta spec ↔ Design Doc agree (the split + flag were applied to both during design).
- `encoding-eval` correctly absent (split to a follow-up change).

## Issues

- CRITICAL: none.
- WARNING: none.
- SUGGESTION / tech-debt:
  - **Dual-copy `nethack_core`**: `map_model.py` (and all `nethack_core` modules) must be kept byte-identical in the repo-root workspace package and the `environments/nethack/` env-bundled copy. Manual sync is fragile — candidate for a future packaging-cleanup change.
  - Item `obj_class` derives from the tty char (not `glyph_to_obj`), so an item under a monster overlay falls back to "object"; trap *type* and open/broken door states are not yet surfaced (locations are). Spec-permitted omissions; future enrichment.
  - Pre-existing pyright diagnostics in `nethack.py` (nle resolution, `CoreObservation` unions, unused vars) are refactor cruft, not this change.

## Assessment

No critical or warning issues. All 15 scenarios covered, full suite green modulo the documented baseline. **Ready for archive.**
