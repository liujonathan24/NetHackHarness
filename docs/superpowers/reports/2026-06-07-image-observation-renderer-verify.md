# Verification Report: image-observation-renderer

Date: 2026-06-07 · Mode: full · Branch: image-observation-renderer

## Summary

| Dimension | Status |
|---|---|
| Completeness | 10/10 tasks checked; 3/3 requirements implemented |
| Correctness | 13/13 spec scenarios covered by tests |
| Coherence | Matches Superpowers Design Doc + delta spec; 1 WARNING resolved |

## Completeness

- `tasks.md`: 10/10 checkboxes `[x]`, 0 incomplete.
- Requirements implemented:
  - *Glyph-to-image rendering* → `nethack_harness/prompt/image_render.py`
  - *IMG and IMG_TTY variants* → `nethack_harness/prompt/prompt_spec.py` (`_image_template`, registry entries) + `rendering.py` (`include_map`/`include_local` gates)
  - *Multimodal-capable env response* → `nethack_harness/prompt/content.py` + `nethack.py` env_response (both return sites)

## Correctness — scenario → test

| Scenario | Test |
|---|---|
| Tile render via GlyphMapper | `test_glyphs_to_png_b64_is_1264x336` |
| Tty-text render via PIL | `test_tty_to_png_b64_returns_valid_png` |
| Strict failure on missing dependency | `test_glyph_path_strict_raises_without_minihack`, `test_tty_path_strict_raises_without_pil` |
| Module imports without optional deps | `test_module_does_not_bind_optional_deps_at_module_level` |
| IMG variant emits multimodal message | `test_img_template_emits_multimodal_list` |
| IMG_TTY uses the tty-text path | `test_img_tty_template_uses_tty_path` |
| IMG text omits spatial text channels | `test_img_template_emits_multimodal_list`, `test_include_local_false_drops_local_blocks` |
| Existing variants unchanged | `test_defaults_unchanged` + `test_integration` (end-to-end string path) |
| String observation with prefix | `test_str_with_prefix_matches_legacy_join` |
| List observation with prefix | `test_list_with_prefix_prepends_text_block` |
| List observation without prefix | `test_list_without_prefix_unchanged` |

Bonus coverage: `test_to_data_uri_prefix`, `test_dict_obs_supported`, `test_content_to_text_string_passthrough`, `test_content_to_text_joins_all_text_blocks`.

## Test evidence

- Feature set in isolation: 19 passed.
- Full suite: **347 passed / 8 failed**. The 8 failures are EXACTLY the pre-existing baseline (`test_hub_install_e2e`, `test_integration::test_success_reward_zero_then_one`, 6 × `test_rewards`) — reward-test pollution from `test_integration` + a packaging bug in `nethack.py:26`, all orthogonal to this change. Baseline was 330/8 → now 347/8 (+17 passing, **zero new failures**).

## Security

No hardcoded secrets; no new `unsafe`/`exec` surfaces (the pre-existing code-mode executor was not touched).

## Issues

- CRITICAL: none.
- WARNING (RESOLVED): open-phase `design.md` carried pre-strict "IMG falls back to tty" language contradicting the approved strict/fail-fast design. Resolved this phase by aligning `design.md` to strict (commit `99249ca`); delta spec + Superpowers Design Doc were already strict.
- SUGGESTION: image-variant trace text for older compacted turns drops the status line (helpers.py `_msg_content` returns "" for list content) — sensible token control, undocumented asymmetry vs ASCII variants. Non-blocking.

## Out-of-scope notes (refactor "Base" layer, not this change)

- `nethack.py:26` `from environments.nethack import harness_overlay` packaging bug → `test_hub_install` failure.
- pyright diagnostics: `nethack.py:1139` (TierName type), `:919` (unused params).
- The working tree carries the uncommitted `nethack_core → nethack_harness` reorg (environmental Base layer per the program roadmap).

## Assessment

No critical issues. All scenarios covered, all feature tests green, byte-identity for existing variants proven. **Ready for archive.**
