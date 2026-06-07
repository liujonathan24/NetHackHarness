# Comet Design Handoff

- Change: image-observation-renderer
- Phase: design
- Mode: compact
- Context hash: 8f299f3d1e23e29900e2e24c6c57c73d84268dde6a5593b98b763d526689f757

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/image-observation-renderer/proposal.md

- Source: openspec/changes/image-observation-renderer/proposal.md
- Lines: 1-55
- SHA256: 7a9b1295faf9d509c014a9e6f037cbdb9cde6045116ee1789bf25f89c04a09e7

```md
## Why

Every shipped variant feeds the model a *text* observation (ASCII grid, BALROG
prose, glyph-box). We have no way to evaluate a vision model on NetHack from a
*rendered image* of the dungeon — the modality real players actually use. The
prompt factory was already built to support this (`ObsSpec.mode` documents
`"ascii" / "img"`, `turn_template` is typed `-> str | list`), but no variant
exercises the image path yet. This change lands that last piece.

## What Changes

- Add an image renderer that converts NLE's `glyphs` grid into a NetHack tile
  PNG (base64), using MiniHack's `GlyphMapper` as the primary path and a PIL
  tty-text renderer as a fallback when MiniHack/PIL are unavailable.
- Register two new variants, `IMG` and `IMG_TTY`, in `VARIANT_REGISTRY`. Their
  `turn_template` emits an OpenAI-multimodal **content list** — a base64 PNG
  `image_url` plus a text block carrying the status/inventory text — instead of
  a plain string. `IMG` uses the GlyphMapper tiles; `IMG_TTY` uses the tty-text
  fallback path.
- Generalize `env_response` so the per-turn user message wraps either a string
  **or** a content-list into `vf.UserMessage`. The per-turn `prefix_parts`
  (autohalt / refiner / multi-tool / feedback strings) currently prepend via
  string join; a small helper injects that prefix text into either shape.

## Capabilities

### New Capabilities
- `image-observation`: rendering the NLE observation as an image and delivering
  it to the model as a multimodal user message, including the variant
  registration and the env-response message-shape generalization that the image
  path requires.

### Modified Capabilities
<!-- None. The ASCII variants' rendered bytes are unchanged; this only adds new
     variants and a content-shape branch that the existing string path falls
     through unchanged. -->

## Impact

- **New file**: `nethack_harness/prompt/image_render.py` (glyphs → base64 PNG;
  GlyphMapper primary, PIL tty fallback).
- **Modified**: `nethack_harness/prompt/prompt_spec.py` — two new
  `VARIANT_REGISTRY` entries (`IMG`, `IMG_TTY`) with `ObsSpec(mode="img")` and
  multimodal `turn_template`s.
- **Modified**: `nethack.py` — `env_response` (two return sites, ~503 journal
  short-circuit and ~890 main) generalized to accept `str | list` content via a
  shared compose helper.
- **Dependencies**: MiniHack + PIL (both already importable in this env: nle
  1.3.0, minihack, GlyphMapper, PIL 10.0.1). The fallback keeps the harness
  importable where they are absent.
- **Data source**: `state["raw_obs"].glyphs` (21×79 ints) for tiles;
  `.tty_chars` / `.tty_colors` for the fallback. No `turn_template` signature
  change (it already receives `state`).
- **Out of scope**: no change to ASCII/BALROG/glyph-box rendered bytes; no new
  tools or skills; no scoring/reward changes.
```

## openspec/changes/image-observation-renderer/design.md

- Source: openspec/changes/image-observation-renderer/design.md
- Lines: 1-79
- SHA256: 8b66fc2813e23056b77eb518f77ca5fb47a6548abbf75f6a9980884f0f6a1e9b

```md
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
- Keep the harness importable when MiniHack/PIL are absent (graceful fallback).
- Leave every existing ASCII/BALROG/glyph-box variant byte-for-byte unchanged.

**Non-Goals:**
- No reward/scoring changes; no new tools or skills.
- No image caching/perf optimization beyond a correct, deterministic render.
- No change to the `turn_template` signature (it already receives `state`).

## Decisions

- **Renderer as a standalone module** (`prompt/image_render.py`) exposing a
  small surface: `glyphs_to_png_b64(raw_obs) -> str` (GlyphMapper path) and
  `tty_to_png_b64(raw_obs) -> str` (PIL fallback path), plus a data-URI helper.
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
  eval matrix can name them and the fallback path is independently testable even
  where MiniHack is installed. Both reuse the same status/inventory text block.

## Risks / Trade-offs

- [GlyphMapper import/runtime failure mid-rollout] → the IMG template falls back
  to the tty-text raster (same path as IMG_TTY) rather than crashing the turn.
- [Multimodal message breaks a downstream text-only consumer (trace writer,
  refiner window)] → reuse refiner's existing flatten-to-text branch; trace
  writer records the text block, noting the image was elided.
- [Large base64 PNG inflates token/transport cost] → keep tile output at native
  GlyphMapper resolution; out-of-scope to downscale now, flagged as future work.
- [PIL/MiniHack absent in CI] → fallback keeps import + IMG_TTY working; IMG
  degrades to the tty raster, so tests stay green without the tile stack.

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
```

## openspec/changes/image-observation-renderer/tasks.md

- Source: openspec/changes/image-observation-renderer/tasks.md
- Lines: 1-21
- SHA256: 5426e8cafdbce25b4726d2843c3e410c5881ddb896a09a047ad4a25a1fae2205

```md
## 1. Image renderer module

- [ ] 1.1 Create `nethack_harness/prompt/image_render.py` with lazy/optional imports of `minihack` and `PIL` (module imports cleanly when both are absent).
- [ ] 1.2 Implement `glyphs_to_png_b64(raw_obs) -> str` using MiniHack `GlyphMapper` over `raw_obs.glyphs`, returning a base64 PNG string.
- [ ] 1.3 Implement `tty_to_png_b64(raw_obs) -> str` PIL fallback rasterizing `raw_obs.tty_chars` / `tty_colors`.
- [ ] 1.4 Add a `render_observation_png_b64(raw_obs, *, mode)` entry point that selects tile vs tty and falls back to tty-text when the tile path is unavailable or raises; add a `data:image/png;base64,...` data-URI helper.

## 2. IMG / IMG_TTY variants

- [ ] 2.1 Add an image-mode multimodal `turn_template` in `prompt_spec.py` that builds the `[image_url, text]` content list from `state["raw_obs"]` plus the status/inventory text block.
- [ ] 2.2 Register `IMG` (GlyphMapper tiles) and `IMG_TTY` (tty fallback) in `VARIANT_REGISTRY` with `ObsSpec(mode="img")`.

## 3. env_response generalization

- [ ] 3.1 Add `_compose_user_content(obs, prefix_parts) -> str | list` that reproduces the current string join for `str` and prepends a text block for a content `list`.
- [ ] 3.2 Route both `env_response` return sites (`nethack.py` ~503 journal short-circuit and ~890 main) through the helper.

## 4. Verification

- [ ] 4.1 Unit-test the renderer (tile path, forced tty fallback, import without optional deps) and `_compose_user_content` (str+prefix, list+prefix, list no-prefix).
- [ ] 4.2 Confirm an `IMG` rollout emits a multimodal message and that existing variants (`B1`, `B`, `G`) produce byte-identical string output; run the existing test suite green.
```

## openspec/changes/image-observation-renderer/specs/image-observation/spec.md

- Source: openspec/changes/image-observation-renderer/specs/image-observation/spec.md
- Lines: 1-84
- SHA256: 1fdb7661f1555c0af454d9aaff59e5dcf9ab583051a8611ffad4bf7acd74a561

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: Glyph-to-image rendering

The harness SHALL provide an image renderer module exposing two explicit,
strict render paths that each return a base64-encoded PNG of the NLE
observation:

- a GlyphMapper tile path that rasterizes the observation's `glyphs` grid into
  NetHack tiles, and
- a PIL tty-text path that rasterizes the observation's `tty_chars` /
  `tty_colors`.

Each path SHALL fail fast: when its required optional dependency (MiniHack/PIL
for the tile path, PIL for the tty path) is unavailable, or when rendering
raises, the path SHALL raise a clear error rather than silently substituting the
other path. The renderer module SHALL remain importable when MiniHack and PIL
are absent; optional dependencies SHALL be resolved only when a render is
actually requested.

#### Scenario: Tile render via GlyphMapper
- **WHEN** the GlyphMapper path is given an observation whose `glyphs` grid is available and MiniHack/PIL are importable
- **THEN** it returns a base64-encoded PNG string produced from the GlyphMapper tile image

#### Scenario: Tty-text render via PIL
- **WHEN** the tty-text path is given an observation and PIL is importable
- **THEN** it returns a base64-encoded PNG string produced from the observation's `tty_chars` / `tty_colors`

#### Scenario: Strict failure on missing dependency
- **WHEN** a render path is invoked but its required optional dependency is unavailable, or rendering raises
- **THEN** the path raises a clear error and does NOT silently fall back to the other render path

#### Scenario: Module imports without optional deps
- **WHEN** the image-render module is imported in an environment lacking MiniHack and PIL
- **THEN** the import succeeds and the optional dependencies are only resolved when a render is actually requested

### Requirement: IMG and IMG_TTY variants

The variant registry SHALL include an `IMG` variant and an `IMG_TTY` variant,
each using an image-mode observation spec. Their per-turn template SHALL emit an
OpenAI-multimodal content list containing an `image_url` entry (a base64 PNG
data URI) and a text entry. The text entry SHALL carry the journal, status, and
inventory blocks only; it SHALL NOT include the ASCII map, the under-player
block, the adjacent-tiles block, or next-action hints (the image is the sole
spatial channel). `IMG` SHALL use the GlyphMapper tile path; `IMG_TTY` SHALL use
the tty-text path. The rendered bytes of all pre-existing (ASCII / BALROG /
glyph-box) variants SHALL remain unchanged.

#### Scenario: IMG variant emits multimodal message
- **WHEN** a rollout runs with variant `IMG`
- **THEN** each per-turn user message content is a list containing an `image_url` (base64 PNG data URI) of the GlyphMapper tiles and a text block with the journal, status, and inventory text only

#### Scenario: IMG_TTY variant uses the tty-text path
- **WHEN** a rollout runs with variant `IMG_TTY`
- **THEN** each per-turn user message content is a list containing an `image_url` rendered from the tty-text path and a text block with the journal, status, and inventory text only

#### Scenario: IMG text omits spatial text channels
- **WHEN** the IMG or IMG_TTY text block is built
- **THEN** it contains no ASCII map, under-player, adjacent-tiles, or next-action-hint content

#### Scenario: Existing variants unchanged
- **WHEN** a rollout runs with any pre-existing variant (e.g. `B1`, `B`, `G`)
- **THEN** the per-turn user message content is a string identical to the pre-change output

### Requirement: Multimodal-capable env response

The environment's per-turn response assembly SHALL wrap either a string or a
multimodal content list into the user message. When per-turn prefix parts
(autohalt, refiner, multi-tool, and feedback notices) are present, they SHALL be
injected into a string observation by the existing join and into a list
observation as a prepended text block, so that no prefix information is lost in
either shape.

#### Scenario: String observation with prefix
- **WHEN** the per-turn template returns a string and one or more prefix parts are present
- **THEN** the user message content is the prefix parts joined ahead of the observation string, identical to the pre-change behavior

#### Scenario: List observation with prefix
- **WHEN** the per-turn template returns a multimodal content list and one or more prefix parts are present
- **THEN** the user message content is a list whose first element is a text block carrying the prefix parts, followed by the image and text entries
```

Full source: openspec/changes/image-observation-renderer/specs/image-observation/spec.md

