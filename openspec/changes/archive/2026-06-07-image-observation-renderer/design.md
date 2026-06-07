## Context

The prompt factory (`nethack_harness/prompt/prompt_spec.py`) resolves each
variant to a `PromptSpec` whose `turn_template(structured, journal, state, *,
compact, journal_max_chars)` renders the per-turn user message. The type is
already `-> str | list` and `ObsSpec.mode` already documents `"ascii" / "img"`,
but every shipped variant returns a string and `env_response` assembles the
message as `vf.UserMessage(role="user", content=obs_text)` at two sites
(`nethack.py:503` journal short-circuit, `nethack.py:890` main path). The main
path also prepends `prefix_parts` with `"\n".join(parts) + "\n\n" + obs_text` —
the only place that hard-assumes a string.

The raw NLE observation lives on `state["raw_obs"]` and exposes `.glyphs`
(21×79 ints), `.tty_chars`, and `.tty_colors`. MiniHack's `GlyphMapper`, PIL,
and NLE are all importable in this environment, so the tile path is the primary
one and the tty-text path is a true fallback for leaner installs.

## Goals / Non-Goals

**Goals:**
- Render the NLE observation as a NetHack tile image and deliver it to the model
  as a multimodal user message (`image_url` + text status/inventory block).
- Ship two variants: `IMG` (GlyphMapper tiles) and `IMG_TTY` (tty-text raster).
- Keep the renderer module importable when MiniHack/PIL are absent (lazy imports;
  a render path only raises when actually invoked without its dependency).
- Leave every existing ASCII/BALROG/glyph-box variant byte-for-byte unchanged.

**Non-Goals:**
- No reward/scoring changes; no new tools or skills.
- No image caching/perf optimization beyond a correct, deterministic render.
- No change to the `turn_template` signature (it already receives `state`).

## Decisions

- **Renderer as a standalone module** (`prompt/image_render.py`) exposing a
  small surface: `glyphs_to_png_b64(raw_obs) -> str` (GlyphMapper path) and
  `tty_to_png_b64(raw_obs) -> str` (PIL tty-text path), plus a data-URI helper.
  Both paths are STRICT: each raises if its optional dependency is missing or the
  render fails — there is no silent cross-fallback between them.
  Rationale: keeps heavy/optional imports (`minihack`, `PIL`) out of
  `prompt_spec` import time; imports happen lazily inside the variant template.
  *Alternative considered:* inline in `rendering.py` — rejected, it would pull
  optional deps into the hot import path used by every ASCII variant.
- **Multimodal content shape = OpenAI list**: `[{"type": "image_url",
  "image_url": {"url": "data:image/png;base64,..."}}, {"type": "text", "text":
  <status/inventory block>}]`. Rationale: matches the verifiers/OpenAI message
  contract the harness already targets; `refiner.py` already has a
  "multimodal — flatten to text where possible" branch to lean on.
- **`env_response` generalization via one helper**: `_compose_user_content(obs,
  prefix_parts) -> str | list`. For a `str` obs it reproduces the exact current
  join; for a `list` obs it prepends a `{"type": "text"}` block built from
  `prefix_parts`. Both return sites call it. Rationale: single seam, ASCII path
  output is unchanged.
- **IMG vs IMG_TTY split**: distinct variants rather than a runtime flag, so the
  eval matrix can name them and the tty-text path is independently testable even
  where MiniHack is installed. Both reuse the same status/inventory text block.
- **STRICT failure (no cross-fallback)**: `IMG` always uses GlyphMapper and
  `IMG_TTY` always uses the tty raster; a missing dependency or render error
  raises rather than silently degrading IMG → tty. Rationale: a clean eval signal
  (a degraded run is never silently mislabelled as IMG); a broken/missing tileset
  surfaces immediately. *Alternative considered:* graceful IMG → tty fallback —
  rejected because it would muddy the encoding comparison.

## Risks / Trade-offs

- [GlyphMapper import/runtime failure mid-rollout] → STRICT: the IMG path raises
  rather than silently degrading to the tty raster. Mitigation: validate the tile
  path early (at variant resolution / first turn) so it fails fast and visibly.
- [Multimodal message breaks a downstream text-only consumer (trace writer,
  refiner window)] → reuse refiner's existing flatten-to-text branch; the trace
  writer records the joined text block(s), noting the image was elided.
- [Large base64 PNG inflates token/transport cost] → keep tile output at native
  GlyphMapper resolution; out-of-scope to downscale now, flagged as future work.
- [PIL/MiniHack absent in CI] → the renderer module still imports (lazy); IMG and
  IMG_TTY each raise only when actually invoked without their dependency. The
  feature tests that exercise rendering require the deps; CI must install them.

## Migration Plan

Additive only. New file + two registry entries + one helper at two call sites.
No data migration. Rollback = revert the three edits; existing variants are
untouched, so no state or config compatibility concerns.

## Open Questions

- Final image dimensions / whether to downscale for token budget (deferred;
  native resolution for v1).
- Whether `IMG` should also include the ASCII grid as text alongside the image
  (v1: image + status/inventory only, no ASCII grid duplication) — to confirm in
  the design/brainstorming phase.
