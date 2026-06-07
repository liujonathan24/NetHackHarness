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
