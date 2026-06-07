## Why

Every observation modality so far hands the model a form it parses poorly: ASCII
art (hard for LLMs), and rendered pixels (hard for VLMs — the `IMG`/`IMG_TTY`
work). The bet of this change is that a **structured-text** encoding of the map
(JSON, and a token-frugal TOON variant) reads better than either, and that the
map is most useful to a code-driven agent as a **queryable object** rather than a
string. We also need to *measure* this — a benchmark comparing encodings head to
head. This is Group A of the program roadmap
(`docs/roadmap/2026-06-07-nethack-program-roadmap.md`).

## What Changes

- Add a **canonical map model** in `nethack_core`: the 21×79 glyph grid (+ tty,
  blstats) converted into a typed entity list (player, monsters/pets, items,
  stairs, doors, traps, features — each with `(x, y)` coords and a description)
  plus a compact grid. Built by reusing NLE's glyph classifiers
  (`glyph_is_monster/pet/object/trap`, `glyph_to_mon/obj/cmap`) and the existing
  `_glyph_kind` / `_FEATURE_GLYPHS` helpers — not a hand-rolled glyph table.
- Add **JSON** and **TOON** observation variants to `VARIANT_REGISTRY` (siblings
  to ASCII `B1`, `IMG`, `IMG_TTY`) that serialize the canonical model into the
  user message. The model is a **sparse entity-list + compact (RLE) grid** (not a
  dense per-tile dump). TOON is a token-frugal encoding of the same model. A
  **`map_detail` config flag (`full` | `minimal`)** selects how much the encoders
  emit — `full` = the rich entity attributes + grid; `minimal` = entity kind +
  coord + short description (grid omitted). One encoder per format projects the
  one canonical model at the selected detail.
- Expose the map as a **code-interpretable object** `nh.map` in the existing
  code-mode `nh` namespace (`nh.map.at(x, y)`, `nh.map.monsters`, `nh.map.stairs`,
  `nh.map.entities`, player position), extending the current `nh.map_view` string.

## Capabilities

### New Capabilities
- `canonical-map-model`: rich typed entity model (entities with coords + per-kind
  attributes + compact grid) derived from NLE glyphs/tty/blstats, in
  `nethack_core`. The shared substrate the other capabilities (and Group B's
  interface) consume.
- `structured-map-observation`: `JSON` and `TOON` variants serializing the
  canonical model into the per-turn user message, at a selectable `map_detail`
  level (`full` | `minimal`).
- `code-interpretable-map`: `nh.map` queryable object in the code-mode namespace.

### Modified Capabilities
<!-- None. ASCII / IMG / IMG_TTY variants and their rendered bytes are unchanged;
     this adds new variants + a new model + a new code-namespace member.

     NOTE: the encoding-eval benchmark (comparing ASCII/IMG/IMG_TTY/JSON/TOON
     across models) was SPLIT OUT of this change into a follow-up change, so the
     observation substrate ships first and the eval design isn't rushed. -->

## Impact

- **New** `nethack_core` map-model module (entity model + glyph classification
  reusing NLE helpers).
- **New** encoders: JSON serializer + a small in-repo TOON encoder (no maintained
  Python TOON package exists).
- **Modified** `nethack_harness/prompt/prompt_spec.py` (`JSON`/`TOON` registry
  entries + templates, `map_detail` flag) and `nethack_harness/tools/code_mode.py`
  (`nh.map`).
- **Dependencies**: none new (TOON encoder is in-repo; glyph classification via
  already-present `nle`).
- **Out of scope**: the encoding-eval benchmark (split to a follow-up change); RL
  training; Group B (pysc2 interface, customizable game); no change to ASCII/IMG
  rendered bytes.
