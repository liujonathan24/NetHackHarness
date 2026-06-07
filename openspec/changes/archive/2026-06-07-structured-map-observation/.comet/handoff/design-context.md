# Comet Design Handoff

- Change: structured-map-observation
- Phase: design
- Mode: compact
- Context hash: 9772c64d2452a78062ff44174e3962c466b356f47fb5e97ea433f1fb2d0cdd28

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/structured-map-observation/proposal.md

- Source: openspec/changes/structured-map-observation/proposal.md
- Lines: 1-65
- SHA256: 00b4bb3bacea2c1093af8445c7a7299f088ede537f6f5eb40e55595c7a8dec0f

```md
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
```

## openspec/changes/structured-map-observation/design.md

- Source: openspec/changes/structured-map-observation/design.md
- Lines: 1-58
- SHA256: 915238ac3c82fc3f619b132632e6af649d1511285ae38ae2e9035a1b310a3860

```md
## Context

`nethack_core/observations.py` already produces a `StructuredObservation`
(`map_view` ASCII, typed `inventory`, `status`, `character`, `adjacent`,
`under_player`). It lacks a typed **entity list with coordinates** — the piece a
structured-text encoding and a code-queryable map both need. NLE exposes the
classifiers to build it cheaply (`nle.nethack.glyph_is_monster/pet/object/trap`,
`glyph_to_mon/obj/cmap`, `GLYPH_*_OFF`); the repo already has `_glyph_kind`,
`_FEATURE_GLYPHS`, and `extract_adjacent`. Variants register in
`VARIANT_REGISTRY`; the `nh` code namespace already exposes `nh.map_view`.

## Goals / Non-Goals

**Goals:**
- One canonical, typed map model (entities + compact grid) built once in
  `nethack_core`, reused by JSON obs, TOON obs, `nh.map`, and (later) Group B.
- `JSON` and `TOON` observation variants; existing variants byte-identical.
- `nh.map` queryable object for code-mode agents.
- A benchmark comparing encodings (ASCII/IMG/IMG_TTY/JSON/TOON) on real metrics.

**Non-Goals:**
- No RL training. No Group B work. No change to ASCII/IMG rendered bytes.
- No dense per-tile JSON dump (sparse entity-list + compact grid instead).

## Decisions (high-level; deep design in /comet-design)

- **Map model in `nethack_core`** (layer-1), not `nethack_harness` (layer-2), so
  Group B's interface can reuse it without depending on the prompt layer.
- **Sparse entity-list + compact grid**, not dense per-tile JSON — controls token
  cost (the whole point of preferring TOON over verbose JSON).
- **Glyph classification reuses NLE helpers** — never a hand-maintained table.
- **TOON encoder is in-repo** (no maintained PyPI package) — a small serializer
  over the same model the JSON path uses; both consume one model so they can't
  diverge.
- **`nh.map` wraps the model** read-only, mirroring how `nh.status`/`nh.inventory`
  expose read-only views today.
- **Eval reuses existing instrumentation** (`test_eval_instrument.py` summarizer,
  `configs/eval/`, `balrog.py` progression) rather than a new metrics stack.

## Risks / Trade-offs

- [TOON spec ambiguity — no reference Python lib] → define a small, documented
  in-repo encoding; test round-trip/shape rather than chase an external spec.
- [Entity classification fidelity] → reuse NLE classifiers + existing helpers;
  test against known fixtures (a monster, an item, stairs, a door).
- [Scope: 4 capabilities is large] → sequence map-model → encodings → nh.map →
  eval; if the eval harness balloons past the build plan, split it into its own
  change (Comet 50% threshold rule).
- [Token cost of JSON] → sparse model + measure tokens/turn as a first-class eval
  metric; TOON exists to undercut JSON.

## Open Questions (for /comet-design)

- Exact entity schema (fields per entity; how much description vs raw glyph id).
- TOON encoding shape (delimiter/format) and how compact to go.
- Whether the grid is included in JSON/TOON or entities-only (lean: compact grid +
  entities).
- Eval matrix size for v1 (which LLM + which VLM; how many seeds/episodes).
```

## openspec/changes/structured-map-observation/tasks.md

- Source: openspec/changes/structured-map-observation/tasks.md
- Lines: 1-20
- SHA256: fcac4a2f51be8cc949c65d3a75da9e0d24ebdef177584000dabf8987fd887cb3

```md
## 1. Canonical map model

- [ ] 1.1 Add a typed map-model module in `nethack_core` (entities with kind/glyph/(x,y)/description, player position, compact grid).
- [ ] 1.2 Implement glyph→entity classification reusing NLE classifiers (`glyph_is_*`, `glyph_to_*`, `GLYPH_*_OFF`) + existing `_glyph_kind`/`_FEATURE_GLYPHS`.
- [ ] 1.3 Build the model from the existing observation pipeline (reuse `StructuredObservation` status/inventory; don't re-parse).
- [ ] 1.4 Unit-test classification against fixtures (monster, item, stairs, door, player position).

## 2. Encoders + JSON/TOON variants

- [ ] 2.1 JSON serializer for the canonical model, honoring `map_detail` (full = rich entities + RLE grid + status/inventory; minimal = kind/coord/desc + status/inventory).
- [ ] 2.2 In-repo TOON encoder for the same model + `map_detail` (deterministic; documented format; more compact than JSON).
- [ ] 2.3 Register `JSON` and `TOON` variants in `VARIANT_REGISTRY` with templates emitting the serialized model; wire the `map_detail` config flag; keep existing variants byte-identical.
- [ ] 2.4 Tests: JSON shape, TOON determinism + more-compact-than-JSON, full-vs-minimal detail, existing variants unchanged.

## 3. Code-interpretable map (nh.map)

- [ ] 3.1 Add a read-only `nh.map` object (player, entities, `at(x,y)`, `monsters`, `stairs`) to the code-mode `nh` namespace backed by the canonical model.
- [ ] 3.2 Tests: query by coordinate, convenience accessors, read-only semantics.

<!-- encoding-eval harness split into a follow-up change (per design decision). -->
```

## openspec/changes/structured-map-observation/specs/canonical-map-model/spec.md

- Source: openspec/changes/structured-map-observation/specs/canonical-map-model/spec.md
- Lines: 1-40
- SHA256: ca9fb3017456214342287b24c74128dcf752887edceb40e9a9d45a21887b23d6

```md
## ADDED Requirements

### Requirement: Typed map model from NLE observation

The harness SHALL provide a canonical map model, built in `nethack_core`, that
converts an NLE observation (glyph grid, tty, blstats) into a typed structure
containing: the player position, a list of typed entities, and a compact
representation of the walkable/visible grid. Each entity SHALL have a kind
(monster, item, stair, door, trap, or feature), a glyph id, an `(x, y)`
coordinate, and a human-readable description, PLUS rich kind-specific attributes
wherever the observation exposes them: monster species and pet flag
(`glyph_to_mon`, `glyph_is_pet`); item object class (`glyph_to_obj`); stair
direction (up/down); door state (open/closed/broken); trap type
(`glyph_to_trap`). The model is the rich superset; encoders may project a subset
(see structured-map-observation `map_detail`). Glyph classification SHALL reuse
NLE's glyph classifiers (`glyph_is_monster`, `glyph_is_object`, `glyph_to_mon`,
`glyph_to_obj`, `glyph_to_trap`, `glyph_to_cmap`, `GLYPH_*_OFF`) and the existing
repo helpers rather than a hand-maintained glyph table. Attributes the
observation does NOT expose (e.g. monster hostile/peaceful disposition, which is
not in the glyph stream) MAY be omitted.

#### Scenario: Monster classified with coordinates and rich attributes
- **WHEN** the model is built from an observation whose glyph grid contains a monster glyph at a tile
- **THEN** the model includes an entity with kind "monster", that glyph id, the tile's `(x, y)`, a description, the species, and a pet flag

#### Scenario: Item classified with object class
- **WHEN** the glyph grid contains an object glyph
- **THEN** the model includes an entity with kind "item" carrying its object class/category

#### Scenario: Stairs and features classified
- **WHEN** the observation contains down-stairs and a door
- **THEN** the model includes a "stair" entity and a "door" entity at their respective coordinates

#### Scenario: Player position present
- **WHEN** the model is built
- **THEN** it exposes the player's `(x, y)` position

#### Scenario: Built from the existing observation pipeline
- **WHEN** the canonical model is produced for a turn
- **THEN** it is derived from the same NLE observation already shaped into `StructuredObservation`, reusing its status/inventory rather than re-parsing them
```

## openspec/changes/structured-map-observation/specs/code-interpretable-map/spec.md

- Source: openspec/changes/structured-map-observation/specs/code-interpretable-map/spec.md
- Lines: 1-23
- SHA256: 4ea9614901dc730ccb30db7df93fdbba5baa823ddc1d1e95293a639cf8e686d5

```md
## ADDED Requirements

### Requirement: nh.map queryable object

The code-mode `nh` namespace SHALL expose a read-only `nh.map` object backed by
the canonical map model, letting agent code query the map structurally instead of
parsing the `nh.map_view` string. `nh.map` SHALL provide at least: the player
position, the full entity list, lookup of what occupies a coordinate
(`nh.map.at(x, y)`), and convenience accessors for common entity kinds (e.g.
`nh.map.monsters`, `nh.map.stairs`). It SHALL be read-only, consistent with the
existing `nh.status` / `nh.inventory` views.

#### Scenario: Query an entity by coordinate
- **WHEN** agent code calls `nh.map.at(x, y)` for a tile occupied by a monster
- **THEN** it returns that entity (kind "monster", with its description)

#### Scenario: Convenience accessors
- **WHEN** agent code reads `nh.map.monsters` and `nh.map.stairs`
- **THEN** each returns the entities of that kind from the current observation

#### Scenario: Read-only
- **WHEN** agent code attempts to mutate `nh.map`
- **THEN** the map state is unaffected (the object is a read-only view), consistent with `nh.status` / `nh.inventory`
```

## openspec/changes/structured-map-observation/specs/structured-map-observation/spec.md

- Source: openspec/changes/structured-map-observation/specs/structured-map-observation/spec.md
- Lines: 1-54
- SHA256: c7733308bcaa95fc1beb5e3f08a418b75d43eee08bd7265a3a564910658f737c

```md
## ADDED Requirements

### Requirement: JSON and TOON observation variants

The variant registry SHALL include a `JSON` variant and a `TOON` variant whose
per-turn template serializes the canonical map model into the user message —
`JSON` as JSON text, `TOON` as a token-frugal TOON encoding of the same model.
Both SHALL be driven by the one canonical map model so the two encodings cannot
diverge. The rendered output of all pre-existing variants (ASCII, IMG, IMG_TTY)
SHALL remain unchanged.

#### Scenario: JSON variant serializes the map model
- **WHEN** a rollout runs with variant `JSON`
- **THEN** the per-turn user message contains JSON text encoding the entity list (with coordinates), the compact grid, and the status/inventory

#### Scenario: TOON variant encodes the same model more compactly
- **WHEN** a rollout runs with variant `TOON`
- **THEN** the per-turn user message contains a TOON encoding of the same canonical model, and its token count is lower than the equivalent JSON encoding

#### Scenario: Existing variants unchanged
- **WHEN** a rollout runs with a pre-existing variant (e.g. `B1`, `IMG`)
- **THEN** its per-turn output is identical to the pre-change output

### Requirement: Selectable detail level

The JSON and TOON encoders SHALL support a `map_detail` configuration flag with
at least the levels `full` and `minimal`. `full` SHALL emit the rich entity
attributes plus the compact grid; `minimal` SHALL emit only each entity's kind,
coordinate, and short description, omitting the grid and the rich per-kind
attributes. Both levels SHALL still include status/inventory. The flag SHALL be a
rollout-level configuration applied to the `JSON` / `TOON` variants (not a
separate set of variants).

#### Scenario: Full detail emits rich attributes and grid
- **WHEN** a rollout runs `JSON` (or `TOON`) with `map_detail=full`
- **THEN** the serialized output includes the rich per-kind entity attributes and the compact grid

#### Scenario: Minimal detail trims to kind/coord/description
- **WHEN** a rollout runs `JSON` (or `TOON`) with `map_detail=minimal`
- **THEN** the serialized output includes only entity kind, coordinate, and short description (no grid, no rich attributes), and is smaller than the `full` output for the same observation

### Requirement: In-repo TOON encoder

Because no maintained Python TOON package exists, the harness SHALL include its
own TOON encoder producing a deterministic, documented encoding of the canonical
map model.

#### Scenario: Deterministic encoding
- **WHEN** the TOON encoder is given the same map model twice
- **THEN** it produces identical output both times

#### Scenario: More compact than JSON
- **WHEN** the same model is encoded as JSON and as TOON
- **THEN** the TOON output uses fewer characters/tokens than the JSON output
```

