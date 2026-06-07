## 1. Image renderer module

- [x] 1.1 Create `nethack_harness/prompt/image_render.py` with lazy/optional imports of `minihack` and `PIL` (module imports cleanly when both are absent).
- [x] 1.2 Implement `glyphs_to_png_b64(raw_obs) -> str` using MiniHack `GlyphMapper` over `raw_obs.glyphs`, returning a base64 PNG string.
- [x] 1.3 Implement `tty_to_png_b64(raw_obs) -> str` PIL fallback rasterizing `raw_obs.tty_chars` / `tty_colors`.
- [x] 1.4 Add a `data:image/png;base64,...` data-URI helper (`to_data_uri`). NOTE: per the design's STRICT decision, there is no combined `render_observation_png_b64` auto-fallback entry point — IMG uses the glyph path and IMG_TTY uses the tty path as two explicit, fail-fast functions (no silent cross-fallback).

## 2. IMG / IMG_TTY variants

- [x] 2.1 Add an image-mode multimodal `turn_template` (`_image_template`) in `prompt_spec.py` that builds the `[image_url, text]` content list from `state["raw_obs"]` plus the journal+status+inventory text block (`include_map=False, include_local=False`).
- [x] 2.2 Register `IMG` (GlyphMapper tiles) and `IMG_TTY` (tty fallback) in `VARIANT_REGISTRY` with `ObsSpec(mode="img")`.

## 3. env_response generalization

- [x] 3.1 Add `compose_user_content(obs, prefix_parts) -> str | list` (in leaf module `nethack_harness/prompt/content.py`, not `nethack.py`, so it is unit-testable without the `import nethack` packaging issue) that reproduces the current string join for `str` and prepends a text block for a content `list`. Plus `content_to_text` for the trace writer.
- [x] 3.2 Route both `env_response` return sites (`nethack.py` ~503 journal short-circuit and ~890 main) through the helper.

## 4. Verification

- [x] 4.1 Unit-test the renderer (tile path, tty path, strict-raise without deps, import without optional deps) and `compose_user_content` (str+prefix, str no-prefix, list+prefix, list no-prefix) + `content_to_text`.
- [x] 4.2 Confirm `IMG`/`IMG_TTY` emit a multimodal message and that existing variants produce byte-identical string output (proven by `test_defaults_unchanged` + `test_integration` end-to-end). Full suite: 347 passed, 8 failed — failure set identical to the pre-existing baseline 8 (reward pollution + hub_install packaging), zero new failures.
