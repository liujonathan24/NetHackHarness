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
