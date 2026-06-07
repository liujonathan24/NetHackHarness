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
